from contextlib import asynccontextmanager

import httpx
import pytest
from main import create_app
from notification_service.config import Settings


@asynccontextmanager
async def client_for(path, **settings):
    settings.setdefault("workers_enabled", False)
    application = create_app(Settings(database_path=str(path), **settings))
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            yield client


@pytest.mark.parametrize("channel", ["email", "sms", "push"])
async def test_create_process_and_retrieve_contract(tmp_path, channel):
    async with client_for(tmp_path / "notifications.db") as client:
        created = await client.post(
            "/v1/requests", json={"to": "recipient", "message": "Hello", "type": channel}
        )
        assert created.status_code == 201
        request_id = created.json()["id"]
        assert isinstance(request_id, str) and request_id
        assert created.json() == {"id": request_id}
        status = await client.get(f"/v1/requests/{request_id}")
        assert status.status_code == 200
        assert status.json() == {"id": request_id, "status": "queued"}
        processed = await client.post(f"/v1/requests/{request_id}/process")
        assert processed.status_code == 202
        assert (await client.get(f"/v1/requests/{request_id}")).json() == {
            "id": request_id,
            "status": "queued",
        }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"to": "recipient", "message": "Hello", "type": "fax"},
        {"to": "recipient", "type": "email"},
        {"to": 123, "message": "Hello", "type": "email"},
        {"to": "recipient", "message": None, "type": "email"},
    ],
)
async def test_invalid_payload_is_rejected(tmp_path, payload):
    async with client_for(tmp_path / "notifications.db") as client:
        response = await client.post("/v1/requests", json=payload)
        assert response.status_code == 422


@pytest.mark.parametrize("method,suffix", [("GET", ""), ("POST", "/process")])
async def test_unknown_id_is_not_found(tmp_path, method, suffix):
    async with client_for(tmp_path / "notifications.db") as client:
        response = await client.request(method, f"/v1/requests/unknown{suffix}")
        assert response.status_code == 404


async def test_requests_and_processing_intent_survive_reopening_database(tmp_path):
    path = tmp_path / "notifications.db"
    async with client_for(path) as client:
        response = await client.post(
            "/v1/requests", json={"to": "recipient", "message": "Hello", "type": "sms"}
        )
        request_id = response.json()["id"]
        assert (await client.post(f"/v1/requests/{request_id}/process")).status_code == 202
    async with client_for(path) as client:
        response = await client.get(f"/v1/requests/{request_id}")
        assert response.json() == {"id": request_id, "status": "queued"}
        assert (await client.post(f"/v1/requests/{request_id}/process")).status_code == 202


async def test_equal_payloads_are_independent_requests(tmp_path):
    async with client_for(tmp_path / "notifications.db") as client:
        payload = {"to": "recipient", "message": "Hello", "type": "email"}
        first = await client.post("/v1/requests", json=payload)
        second = await client.post("/v1/requests", json=payload)
        assert first.json()["id"] != second.json()["id"]


async def test_backlog_capacity_rejects_before_accepting_work(tmp_path):
    async with client_for(tmp_path / "notifications.db", backlog_capacity=1) as client:
        payload = {"to": "recipient", "message": "Hello", "type": "email"}
        assert (await client.post("/v1/requests", json=payload)).status_code == 201
        response = await client.post("/v1/requests", json=payload)
        assert response.status_code == 503
        assert "Retry-After" in response.headers


async def test_readiness(tmp_path):
    async with client_for(tmp_path / "notifications.db") as client:
        assert (await client.get("/health/ready")).status_code == 200
