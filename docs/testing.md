# Testing and reproducible validation

Run from the repository root using a POSIX shell. Install Docker Compose v2,
Python 3.12 and `uv` for local tests. The delivery verifier needs only Python 3.
Generated results belong outside Git; each benchmark should use a new directory.

## Host-port override

Use this **before starting Compose** if host port 5000 is occupied (for example,
by macOS AirPlay). This requires Compose support for `!override`; the documented
setup was verified with Compose 5.5.1:

```sh
cat > /tmp/ams-compose-ports.yaml <<'YAML'
services:
  provider:
    ports: !override
      - "3001:3001"
      - "15000:5000"
YAML
export COMPOSE_FILE="docker-compose.yaml:/tmp/ams-compose-ports.yaml"
export NOTIFY_TEST_BASE_URL="http://127.0.0.1:15000"
docker compose config --quiet
```

Keep these exports in the shell running the remaining commands. The verifier's
Compose subprocess inherits `COMPOSE_FILE`. Internal port 5000 and the original
k6 target `provider:5000` remain unchanged. Without an override, omit this section;
the examples default to host port 5000. Do not switch port mappings on a running
shared network namespace during a test.

## Local tests

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r app/requirements-dev.txt
.venv/bin/pytest -q --cov=notification_service --cov=main --cov-branch
.venv/bin/ruff check app scripts
.venv/bin/ruff format --check app scripts
docker compose config --quiet
```

Tests use temporary SQLite files and HTTPX mock/ASGI transports. Quota and retry
tests inject time, sleep and randomness; they do not depend on provider randomness.
Lease tests use explicit timestamps, competing connections and a subprocess killed
with SIGKILL after its claim commit. Worker concurrency and cancellation tests use
events. Tests cover actual delivery decisions and persisted state, not just HTTP
status codes. Run tests separately from a performance measurement to avoid load
interference, and use a trusted isolated account as noted in the dependency audit.

## Docker and official load test

Start the stack and check readiness:

```sh
docker compose up -d --build --wait app influxdb grafana
curl --fail "${NOTIFY_TEST_BASE_URL:-http://127.0.0.1:5000}/health/ready"
```

Wait for any previous activated backlog to finish, and do not run other producers
or provider-check during this measurement. The following read-only command shows
all retained states; prior terminal records do not need to be deleted:

```sh
docker compose exec -T app python -c 'import os,sqlite3; db=sqlite3.connect("file:"+os.environ["NOTIFY_DATABASE_PATH"]+"?mode=ro",uri=True); print(db.execute("SELECT status,count(*) FROM notifications GROUP BY status").fetchall())'
```

Capture the start time, execute the **original** k6 scenario, then wait for the
entire batch (normally several minutes) and verify every status through the API:

```sh
results_dir=$(mktemp -d /tmp/ams-results.XXXXXX)
python3 -c 'import time; print(time.time())' > "$results_dir/batch-since"
docker compose run --rm --user "$(id -u):$(id -g)" \
  -v "$results_dir:/results" load-test \
  --quiet --summary-export=/results/k6-summary.json
python3 scripts/verify_delivery.py \
  --since "$(cat "$results_dir/batch-since")" \
  --base-url "${NOTIFY_TEST_BASE_URL:-http://127.0.0.1:5000}" \
  --output "$results_dir/delivery.json"
```

The explicit container UID lets k6 write to the temporary directory without making
it world-writable. The verifier exits nonzero for failed/pending jobs or inconsistent
API/provider-confirmation results. An empty batch is rejected. Never reset records
or remove the volume to turn a failed run into a successful one.

Check k6 metrics and **reconcile the batch count**, because a database snapshot
cannot detect records missing entirely. For this unmodified scenario, require all
six checks per iteration and compare iterations with durable requests:

```sh
python3 - "$results_dir" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
k6 = json.loads((root / "k6-summary.json").read_text())
delivery = json.loads((root / "delivery.json").read_text())
metrics = k6["metrics"]
count = int(metrics["iterations"]["count"])
assert count > 0
assert metrics["checks"]["fails"] == 0
assert metrics["checks"]["passes"] == 6 * count
assert metrics["http_req_failed"]["value"] == 0
assert delivery["total"] == count
assert delivery["provider_confirmed_sent"] == count
assert delivery["api_checks_passed"] == count
assert delivery["passed"]
print(f"Verified {count} accepted requests through provider confirmation and API status")
PY
```

k6 has no thresholds: exit zero alone is not acceptance. Report latency, checks,
HTTP failures, delivery duration and attempts even if reconciliation fails. A
stochastic exhaustion may legitimately fail delivery after five attempts. Preserve
that result. SQLite/provider confirmation does not prove inbox arrival or exactly-once
external delivery. See [measured results](validation.md) for environment-specific runs.

## Separate original provider check

Only after the application backlog has drained:

```sh
docker compose run --rm provider-check
```

The original test accepts 429/500 codes but expects an `error` field; the supplied
provider returns `detail`. Its logic check can therefore fail on valid simulated
errors. It also consumes quota and has no thresholds. Keep the discrepancy visible
and record its checks separately from application acceptance.

## Local development without the app container

Use the same virtual environment above and a provider reachable at port 3001.
Do not run another app worker against the provider during a benchmark.

```sh
export NOTIFY_PROVIDER_API_KEY=test-dev-2026
.venv/bin/uvicorn main:app --app-dir app --host 0.0.0.0 --port 5000
```

`NOTIFY_*` settings come from the environment; see
[configuration](../app/notification_service/config.py) and [.env.example](../.env.example).
Unlike Compose variable substitution, direct Uvicorn startup does not load `.env`
automatically. Use a different port if the Docker app is already published there.

## Crash and persistence verification

The deterministic suite already covers real subprocess SIGKILL, lease expiration,
stale-owner rejection and final-attempt exhaustion. For a manual Docker crash test,
create and activate a small batch, wait for a processing state, kill only the app
with `docker compose kill -s SIGKILL app`, then run `docker compose start app`.
Keep SQLite intact and observe recovery after startup cooldown and lease expiration.
An ambiguous external send may duplicate; recovery does not imply exactly-once.

For container recreation, save an existing ID and use
`docker compose up -d --force-recreate --no-deps --wait app`; confirm the same ID
and terminal state remain accessible. Removing the named volume destroys evidence.
These operational tests must run separately from a throughput benchmark.

## Acceptance checklist

- Exact creation/processing/status contracts, including all three channels.
- Creation does not send; repeated process calls do not reopen terminal requests.
- Atomic admission, exclusive live leases and bounded worker concurrency.
- Deterministic quota windows, conservative restart and persistent retry schedules.
- Explicit permanent/transient failures; malformed successes never become sent.
- Expired lease reclamation and terminal handling of exhausted abandoned attempts.
- Original k6 checks, latency and HTTP failure metrics recorded honestly.
- Accepted count reconciled with provider confirmations and every public status.
- Original provider and k6 sources unchanged.
