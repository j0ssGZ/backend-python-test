# Testing and reproducible validation

## Local tests

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r app/requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/pytest -q --cov=notification_service --cov=main --cov-branch
.venv/bin/ruff check app scripts
.venv/bin/ruff format --check app scripts
docker compose config --quiet
```

Tests use temporary SQLite files and HTTPX mock/ASGI transports. Quota and retry
tests inject time, sleep and randomness; they never depend on the real provider's
random failures. Lease tests use explicit timestamps, competing connections and
a subprocess killed with SIGKILL after its claim commit. Worker concurrency tests
coordinate with events, not timing-based sleeps.

## Docker and official load test

```sh
docker compose up -d --build --wait app influxdb grafana
mkdir -p /tmp/ams-results
chmod 777 /tmp/ams-results
python3 -c 'import time; print(time.time())' > /tmp/ams-results/batch-since
docker compose run --rm -v /tmp/ams-results:/results load-test \
  --quiet --summary-export=/results/k6-summary.json
python3 scripts/verify_delivery.py \
  --since "$(cat /tmp/ams-results/batch-since)" \
  --output /tmp/ams-results/delivery.json
```

No provider source or original k6 script needs modification. Capture the start
timestamp immediately before the load test and do not run other producers in the
same batch interval. The verification script waits for terminal states, requires
provider confirmation on every sent row, checks every ID through the public API,
and exits nonzero for failed/pending jobs or inconsistent results. Compare its
reported total with the accepted creation count from k6; a database snapshot
alone cannot detect records that are missing entirely. A successful
SQLite/HTTP verification confirms the provider contract, not real inbox delivery.
If jobs remain queued, keep the app running while inspecting logs and backlog;
do not delete the volume or reset states to produce an artificial success.

The original k6 file has checks but no thresholds. Inspect the exported checks,
HTTP failure rate, iteration counts and latency distributions; exit code zero
alone is not an acceptance criterion. Raw summaries are evidence, not portable
performance guarantees. A stochastic exhaustion can legitimately fail eventual
delivery even when HTTP checks pass; preserve and investigate that result.

The separate original `provider-check` accepts 429/500 codes but expects an
`error` field; the provider actually returns `detail`. Its second check can fail
on valid simulated failures. Running it also consumes the provider's quota.
Run it separately from a clean throughput measurement and record this limitation.

## Port 5000 occupied on macOS

Control Center/AirPlay may already listen on host port 5000. Keep the internal
port and original tests unchanged. With recent Docker Compose, create a temporary
override outside the repository:

```yaml
services:
  provider:
    ports: !override
      - "3001:3001"
      - "15000:5000"
```

Use `docker compose -f docker-compose.yaml -f /tmp/ams-compose-ports.yaml` in the
commands above, and pass both `--compose-file` options and
`--base-url http://127.0.0.1:15000` to `verify_delivery.py`.
This changes only host publication; k6 still targets `provider:5000`.

## Crash test and restart safety

With a small activated batch, wait until an actual processing state is visible,
kill only the app using `docker compose kill -s SIGKILL app`, and start it again.
Do not clear SQLite. Requests should remain queryable and resume after startup
cooldown and lease expiration. A crash during the last allowed attempt ends in
failed after expiration. A provider call interrupted after delivery may duplicate
on recovery; this is an external-contract limitation, not a lease guarantee.

To check container recreation, save an existing ID and use
`docker compose up -d --force-recreate --no-deps --wait app`; its state must remain
available from the named volume. `docker compose down -v` destroys that evidence.

## Acceptance criteria

- Exact 201/202/200 contracts and all three notification channels.
- Creation alone never calls the provider; repeating process never reopens a
  terminal request.
- Atomic capacity admission and single active lease under competing connections.
- Every tested sliding window respects quota, including reopen/startup cases.
- Retryable/permanent failures are classified; malformed success never becomes sent.
- Expired leases recover; stale owners cannot commit; final-attempt crashes terminate.
- Official k6 functional checks pass, with latency and HTTP failures reported.
- Observe the entire accepted batch through terminal states after the load stops.
- Provider and original k6 sources remain byte-for-byte unchanged.
