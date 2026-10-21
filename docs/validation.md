# Validation results

Measurements below are separate executions. The original provider and k6 scripts
were unchanged in both. Raw JSON is retained locally under the ignored
`docs/validation/` directory; it is not part of the Git release. Use the
[testing guide](testing.md) to generate your own evidence.

## Release validation after audit fixes

The original 40-second k6 scenario was rerun on **2026-10-21**, starting at
`20:20:34.494551 UTC`, against application source **`c8ab0a0`**. Running-container
source hashes matched the checkout, including both audit cancellation fixes.
Subsequent release changes are documentation only.

### HTTP acceptance and latency

- Completed iterations / accepted requests: **2,583**.
- Checks: **15,498 passed, 0 failed** (six per iteration).
- HTTP requests: **7,749**, with **0% HTTP failures**.
- All endpoints: mean **35.21 ms**, p95 **235.58 ms**, maximum **637.90 ms**.
- `/process`: mean **35.90 ms**, p95 **239.90 ms**, p99 **556.73 ms**,
  maximum **630.15 ms**, from 2,583 InfluxDB samples.
- Scenario target: 200 VUs; sampled maximum: 199; configured `vus_max`: 200.

The p95 is materially higher than the historical 11.66 ms. No latency threshold
was supplied, and no performance improvement is claimed. This was a shared local
Docker environment with other containers running, retained database history, and
a brief local pytest run overlapping part of k6. These are comparison limitations,
not an established explanation for the difference. A controlled isolated rerun
would be needed to attribute it. The zero exit code alone was not used as proof.

### Actual eventual delivery

- **2,583 provider-confirmed sent; 0 failed; 0 queued/processing at completion.**
- All **2,583 public API status responses** matched the durable records.
- **2,875 attempts**: provider logs corroborated **2,583 HTTP 200**, **292 HTTP 500**
  and **0 HTTP 429** responses during the batch.
- Attempts per request: 2,311 required one; 254 two; 16 three; two four.
- First creation: `2026-10-21T20:20:36.330122+00:00`.
- First creation to last durable completion: **655.10 seconds (10.92 minutes)**.
- Accepted k6 count, persisted batch count, provider confirmations and API checks
  were explicitly reconciled. The pre-run database had 2,721 terminal records and
  no queued/processing backlog; no records were deleted or reset.

`sent` proves the supplied provider's confirmation, not inbox arrival or exactly-once
external delivery. Bounded stochastic retries can produce failed requests on other
runs; this run's complete delivery is an observation, not a universal guarantee.

### Rebuild, persistence and separate provider check

After the batch drained, the documented `docker compose up -d --build --wait app
influxdb grafana` command succeeded with the host-port override. The app and
provider containers were recreated; all **2,583** retained records were verified again through the API.
The same batch totals, provider confirmations and attempt counts were preserved.
This was after the measured run, not a restart injected into its timing.

The original provider-check was then run separately: **18/20 checks passed**.
Provider logs confirmed eight 200s and two simulated 500s; HTTP failure rate was
20%. Both failed checks were `Provider logic is active`, which expects `error`
where the provider returns `detail`. Exit zero did not make those checks pass.
The rebuilt provider used unchanged source; neither the current 18/20 nor the
historical 19/20 result is hidden or conflated with application acceptance.

### Environment and repeatability

Docker Engine **29.7.2** on Docker Desktop, Compose **5.5.1**, Linux **aarch64**,
10 Docker CPUs and
8,319,504,384 bytes of Docker memory. App runtime: Python **3.12.15**, SQLite
**3.46.1**, FastAPI **0.110.0**, Pydantic **2.6.3**, HTTPX **0.27.0**, aiosqlite
**0.20.0**, Uvicorn **0.27.1** and Starlette **0.36.3**. k6: **2.3.0**, commit
`e088784614`, Go 1.27.1, Linux arm64.

The measured app image ID was
`sha256:70f4847be69f77b45ae832e62d5fc0e3b2cc5c1a9845895f114e3d7421840ce1`;
provider image ID was
`sha256:353d1bea48563271d8697d9c28e3dd7778cb9b1e203c0462fc3826105ef62adc`.
Full installed-package versions, image IDs and source hashes are retained in the
local `docs/validation/release-2026-10-21/` evidence directory.
Image tags/transitive dependencies remain mutable; these IDs identify the run,
not a promise that a future rebuild resolves identical artifacts.

Default worker, lease, timeout, retry, quota and capacity settings were used.
The temporary host-port override exposed the API on **15000** while preserving
internal port **5000**, the shared network namespace and original k6 target.
No provider-check or other notification producer ran during the measured batch.

### Tests and documentation checks

The release pass ran **58 tests successfully**, including a second run in a fresh
Python 3.12.14 virtual environment. Coverage: **97.67% statements**, **91.67% branches**,
**96.94% combined**. Ruff lint/format, Compose configuration and whitespace checks
passed. The audit had already passed the same 58 tests in Linux Docker; that is
historical audit evidence, not an additional Linux suite run during this pass.

All four Mermaid diagrams rendered successfully. Internal documentation links and
anchors resolved. Documented local startup was checked using an isolated database
and an available alternative port; Swagger, readiness and Grafana URLs responded.
The five original provider/k6 files still match baseline `8c5c7f5` byte for byte.

## Historical validation before audit fixes

The following measurements describe the earlier **2026-10-20** implementation run,
not the corrected source measured above. The historical source hashes and raw
summaries remain in local `docs/validation/`. Audit fixes and their regression tests
are described in [audit.md](audit.md).

### Tests and static checks

- Milestone 1: 16 tests passed (contracts, SQLite durability and atomic admission).
- Milestone 2: 42 tests passed (provider mapping, quota and persisted retries).
- Milestone 3: 49 tests passed (leases, SIGKILL recovery and competing workers).
- Final suite: 56 tests passed on macOS/Python 3.12.14 and Linux/Python 3.12.15.
- Coverage: 97.89% statements,
  92.86% branches,
  97.30% combined.
- Ruff lint/format, Python compilation, Compose configuration and whitespace
  checks passed.

### Official load test

The original 40-second staged scenario completed 2,706 iterations:

- Checks: 16,236 passed, 0 failed.
- HTTP requests: 8,118; HTTP failure rate: 0%.
- All-endpoint p95: 11.66 ms.
- `/process`: mean 4.91 ms, p95 11.59 ms, p99 85.51 ms, maximum 159.02 ms,
  measured from the run's InfluxDB samples (2,706 calls).
- Original scenario targets 200 VUs; the sampled `vus` maximum was 199 and
  configured `vus_max` was 200.

The lack of thresholds in the supplied script means its zero exit code was not
used as the sole pass criterion. The exported checks and HTTP metrics were inspected.

### Eventual delivery and persistence

First batch request: `2026-10-20T22:46:59.402590+00:00`.

- Accepted: 2,706; provider-confirmed sent: 2,706.
- Failed: 0; queued/processing at completion: 0.
- Provider attempts: 3,000, comprising 2,706 successes,
  294 simulated HTTP 500 failures and zero HTTP 429 responses. Counts were also
  checked against provider logs restricted to this batch interval.
- Attempts per request: 2,444 needed one, 233 needed two, 26 needed three and
  three needed four. No request needed the fifth permitted attempt.
- Time from first creation to final durable success:
  673.47 seconds (11.22 minutes).
- All 2,706 public status responses matched the persisted terminal records.
- Recreating the app container preserved the entire batch; the complete public
  status verification was repeated after recreation.
- A separate real Docker SIGKILL test recovered all 12 notifications across email,
  sms and push in 30.78 seconds, without clearing data or resetting states.

`sent` means a validated provider confirmation. It does not establish exactly-once
recipient delivery; ambiguous failures can duplicate external sends.

### Separate original provider check: known failure retained

The original `health-check.js` was run separately after the load batch drained.
It produced **19/20 passing checks**, with 1 failed check.
One of ten calls received the provider's simulated 500. The response contained
`detail`, while the original `Provider logic is active` check requires `error` or
`provider_id`. The `Provider is responding` check passed. Neither the provider nor
the original check was modified to hide this discrepancy. The provider-check's
HTTP failure metric was 10%; its process still exited zero because it has no thresholds.

### Environment and reproducibility

Docker had 10 CPUs and 8,319,504,384 bytes of memory. The app used Python 3.12.15,
SQLite 3.46.1 and the pinned runtime requirements; k6 was 2.3.0 on Linux arm64.
Performance is environment-specific and random provider outcomes vary.

Host port 5000 was occupied by macOS Control Center. A temporary external Compose
override published app port 5000 on host port 15000. The shared container network,
internal API port and original k6 target remained unchanged. See
[testing.md](testing.md) for the exact override and validation commands.

The locally retained source hashes matched the running app container at the time
of the load test. Protected-file hashes matched Git HEAD for every provider file
and original k6 script. The audit subsequently changed cancellation handling;
these load measurements are historical evidence, not a rerun of the final source.
