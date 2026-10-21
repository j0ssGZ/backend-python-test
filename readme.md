# Notification API — AMS Solutions / Inditex challenge

A durable notification API that accepts email, SMS and push requests, then sends
activated requests through the supplied unreliable provider. The implementation
preserves the challenge's HTTP contracts and Docker network layout. The original
provider and k6 tests are unchanged.

**Stack:** Python 3.12, FastAPI, Pydantic v2, async HTTPX, SQLite/aiosqlite,
pytest and Docker Compose. Small domain, application and infrastructure modules
provide pragmatic hexagonal boundaries without a separate broker.

## Guarantees and scope

- Creation and processing intent are committed before successful API responses.
- Four bounded async workers share one HTTP client. Durable rate reservations
  enforce 50 attempts per sliding 10 seconds, with conservative startup cooldown.
- Retries use persisted schedules, exponential backoff and jitter. Expiring leases
  allow recovery after crashes and prevent stale workers from overwriting results.
- Repeating `/process` is safe. Creation alone does not send; identical creations
  intentionally receive different IDs.
- `sent` requires a validated provider confirmation. **Exactly-once delivery is
  impossible** without provider idempotency or delivery lookup; ambiguous failures
  can duplicate sends. Five attempts do not guarantee every notification succeeds.

This is a single-host technical challenge deployment. Public exposure requires
security hardening; see the [audit and outstanding risks](docs/audit.md).

## Quick start

Requirements: Docker with Compose v2, available host ports 3000/3001/5000, and a
POSIX shell for the examples. Run commands from the repository root. Python 3.12
and `uv` are needed only for local development/tests; the delivery verifier uses
Python 3's standard library.

If macOS AirPlay occupies port 5000, first apply the
[documented host-port override](docs/testing.md#host-port-override).

```sh
docker compose up -d --build --wait app influxdb grafana
curl --fail "${NOTIFY_TEST_BASE_URL:-http://127.0.0.1:5000}/health/ready"
```

Compose supplies the provider's public development credential. Optional settings
are listed in [.env.example](.env.example); create a local `.env` if overriding
Compose defaults. Application data lives in the named `notification-data` volume
and survives app container recreation. Removing the volume deletes that data.

Default endpoints: [API docs](http://localhost:5000/docs),
[provider docs](http://localhost:3001/docs), and
[Grafana scorecard](http://localhost:3000/d/backend-performance-scorecard/).
With the override, API docs move to `http://localhost:15000/docs`.

## HTTP API

- `POST /v1/requests` — JSON `{"to":"recipient","message":"Hello","type":"email"}`;
  returns **201** with `{"id":"<UUID>"}`. Types: `email`, `sms`, `push`.
- `POST /v1/requests/{id}/process` — enables delivery; returns **202**, or **200**
  for an already terminal request, with `{"id":"<UUID>","status":"..."}`.
- `GET /v1/requests/{id}` — returns **200** with ID and
  `queued`, `processing`, `sent` or `failed` status.
- `GET /health/ready` — checks storage and worker liveness; **200** when ready.

Unknown IDs return 404, invalid bodies 422, and backlog/storage unavailability
503. Readiness and a 202 response do not mean delivery is complete. Both newly
registered and activated requests waiting for a worker can be `queued`.

## Review and validation

Start with [architecture and Mermaid diagrams](docs/architecture.md), then use
[testing instructions](docs/testing.md) for local tests, Docker validation, the
original k6 scenario and verification of every accepted request after draining.
The [measured results](docs/validation.md) record benchmark runs separately from
unit-test results. The [audit](docs/audit.md) records corrected defects and
remaining limitations.

The provider allows only a few attempts per second. The 40-second k6 scenario
can enqueue thousands of notifications; keep the service running for minutes
until the backlog drains. Passing HTTP checks alone does not establish delivery.
The separate provider-check discrepancy is documented rather than hidden.
