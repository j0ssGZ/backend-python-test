import httpx
import pytest
from notification_service.domain import Channel, Notification
from notification_service.provider import DeliveryError, HTTPNotificationProvider


def notification():
    return Notification.create("recipient", "Hello", Channel.EMAIL, now=100)


async def test_provider_sends_auth_payload_and_trace_id():
    async def respond(request):
        assert request.headers["X-API-Key"] == "secret"
        assert request.url.path == "/v1/notify"
        assert request.url.params["trace_id"] == item.id
        import json

        assert json.loads(request.content) == {
            "to": "recipient",
            "message": "Hello",
            "type": "email",
        }
        return httpx.Response(200, json={"status": "delivered", "provider_id": "p-1234"})

    item = notification()
    async with httpx.AsyncClient(
        base_url="http://provider",
        headers={"X-API-Key": "secret"},
        transport=httpx.MockTransport(respond),
    ) as client:
        assert await HTTPNotificationProvider(client).send(item) == "p-1234"


@pytest.mark.parametrize(
    "code,retryable",
    [
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (400, False),
        (401, False),
        (403, False),
        (422, False),
        (302, False),
    ],
)
async def test_http_failures_are_explicit(code, retryable):
    async with httpx.AsyncClient(
        base_url="http://provider",
        transport=httpx.MockTransport(lambda _: httpx.Response(code, json={"detail": "error"})),
    ) as client:
        with pytest.raises(DeliveryError) as failure:
            await HTTPNotificationProvider(client).send(notification())
        assert failure.value.retryable is retryable
        assert failure.value.category == f"http_{code}"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "pending", "provider_id": "p-1234"},
        {"status": "delivered"},
        {"status": "delivered", "provider_id": ""},
    ],
)
async def test_invalid_success_is_never_reported_as_delivered(body):
    async with httpx.AsyncClient(
        base_url="http://provider",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    ) as client:
        with pytest.raises(DeliveryError, match="invalid_response") as failure:
            await HTTPNotificationProvider(client).send(notification())
        assert failure.value.retryable is False


async def test_transport_timeout_is_retryable():
    def timeout(request):
        raise httpx.ReadTimeout("ambiguous result", request=request)

    async with httpx.AsyncClient(
        base_url="http://provider", transport=httpx.MockTransport(timeout)
    ) as client:
        with pytest.raises(DeliveryError) as failure:
            await HTTPNotificationProvider(client).send(notification())
        assert failure.value.retryable is True


@pytest.mark.parametrize("header,expected", [("12", 12), ("nonsense", None), ("inf", None)])
async def test_retry_after(header, expected):
    async with httpx.AsyncClient(
        base_url="http://provider",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(429, headers={"Retry-After": header})
        ),
    ) as client:
        with pytest.raises(DeliveryError) as failure:
            await HTTPNotificationProvider(client).send(notification())
        assert failure.value.retry_after == expected
