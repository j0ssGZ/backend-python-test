# Validation results

This records an actual local run against the unmodified supplied provider and
original k6 scripts, before the final audit fixes. Raw JSON evidence is retained
locally in the ignored `docs/validation/` directory and is not versioned.
See [audit.md](audit.md) for validation of the final audited source.

## Tests and static checks

- Milestone 1: 16 tests passed (contracts, SQLite durability and atomic admission).
- Milestone 2: 42 tests passed (provider mapping, quota and persisted retries).
- Milestone 3: 49 tests passed (leases, SIGKILL recovery and competing workers).
- Final suite: 56 tests passed on macOS/Python 3.12.14 and Linux/Python 3.12.15.
- Coverage: 97.89% statements,
  92.86% branches,
  97.30% combined.
- Ruff lint/format, Python compilation, Compose configuration and whitespace
  checks passed.

## Official load test

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

## Eventual delivery and persistence

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

## Separate original provider check: known failure retained

The original `health-check.js` was run separately after the load batch drained.
It produced **19/20 passing checks**, with 1 failed check.
One of ten calls received the provider's simulated 500. The response contained
`detail`, while the original `Provider logic is active` check requires `error` or
`provider_id`. The `Provider is responding` check passed. Neither the provider nor
the original check was modified to hide this discrepancy. The provider-check's
HTTP failure metric was 10%; its process still exited zero because it has no thresholds.

## Environment and reproducibility

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
