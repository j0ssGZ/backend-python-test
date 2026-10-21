# Final engineering audit

## Scope and result

Reviewed the entire implementation diff, untracked source/tests/documentation,
local generated evidence, original API contracts, provider behavior and original
k6 assertions. Work remains on the personal fork's `main`; no push was performed.
The five provider/k6 files match baseline `8c5c7f5` byte for byte.

No critical defect was identified in the challenge's intended local deployment.
Two demonstrated defects were corrected before committing their implementation:

- **High — cancelled transaction startup poisoned the shared connection.**
  `BEGIN IMMEDIATE` was outside the rollback boundary. aiosqlite can execute it
  even when the awaiting coroutine is cancelled, leaving subsequent requests
  unable to start transactions. BEGIN is now inside the exception/rollback
  boundary. The regression test cancels after SQLite starts the transaction and
  proves a subsequent creation commits using the same connection.
- **Medium — quota wait could start new work during shutdown.** A worker could
  acquire quota after stop had been signaled and then claim/send a new job.
  Workers now check stopping before starting an iteration and after acquiring
  quota. An event-controlled test proves no provider call or lease occurs when
  shutdown starts during the quota wait. Already claimed work remains subject
  to graceful draining, cancellation and lease recovery.

Both new tests failed on the previous implementation and passed after correction.
The commits contain the corrected implementation, not deliberately broken stages.

## Contract and behavior assessment

Creation returns exactly 201 and an ID only after commit. Processing durably
records dispatch intent and returns 202, or 200 for terminal requests. Retrieval
returns the documented ID/status contract. All three channels, unknown IDs,
validation failures, capacity rejection and storage errors have tests.
Creation alone never sends. Repeated processing cannot reopen terminal jobs.
Optional creation idempotency remains explicitly deferred.

Transactions are short and serialized per connection; BEGIN IMMEDIATE also
protects competing SQLite connections. Capacity admission and lease reclamation
are atomic. No transaction spans network I/O. Lease tokens and expiration fence
stale completions, including before another worker reclaims the record. Final
attempt crashes eventually become failed when workers resume and storage is
available. Wall-clock jumps and storage failure can delay recovery.

Provider quota reservations and shared cooldown are durable and atomic. Tests
check every simulated sliding window, simultaneous admissions across two
connections, reopening, spacing and conservative startup. Dispatch reservations
cannot guarantee arrival timing at an external server: network delay, clock
changes or unrelated clients can still cause 429. Retries handle this explicitly.

Workers are bounded; the shared HTTPX pool is bounded too. Retry schedules persist
and use capped exponential backoff with jitter. Permanent failures and malformed
successes never become sent. Total attempt deadlines bound calls; shutdown waits
then cancels, leaving abandoned leases recoverable. Exactly-once external delivery
remains impossible with this provider contract.

Tests go beyond k6: real SQLite files, competing connections, stale owners,
SIGKILL in a subprocess, event-controlled worker concurrency, persisted retries,
HTTPX request/response validation and API lifespan integration. Fake clocks and
randomness control the retry/quota tests. Coverage does not prove the absence of
all scheduling races or external side-effect duplication.

## Remaining risks and limitations

- **High if publicly exposed:** the supplied stack has anonymous Grafana admin,
  public development credentials, no application authentication/TLS and published
  ports. It is a local challenge environment, not a production security boundary.
  The app itself runs as a non-root user and does not log recipient/message/key.
  The unchanged provider logs recipients. No private credentials were staged.
- **Medium — dependency advisories:** an actual pip-audit run of the installed
  local environment returned 16 entries, representing eight distinct advisories
  across Starlette 0.36.3 and pytest 8.3.5. Seven Starlette advisories concern form
  parsing, Windows StaticFiles, unconstrained HTTPEndpoint dispatch or URL-based
  security decisions. This API uses none of those features. The pytest advisory
  concerns local users attacking predictable temporary directories on UNIX;
  run tests under a trusted user in an isolated environment. This is an exposure
  assessment, not a clean vulnerability scan. Dependency upgrades require a
  separate compatibility pass; do not suppress these findings. The report is
  retained locally at `/tmp/ams-dependency-audit.json` and not versioned.
- **Medium — resource bounds:** backlog count is bounded, but payload bytes and
  terminal-record disk usage are not. Unactivated requests retain capacity.
  Public deployment needs request-size/admission controls and storage operations.
  Automatic retention remains deferred as agreed.
- **Medium — reproducibility:** direct Python requirements are pinned, but
  transitive dependencies and image tags are not fully locked. Rebuilds can
  resolve different versions; a successful build is not byte reproducibility.
  Production promotion should lock the dependency graph and image digests and
  scan the final image, including OS packages. No OS-image scan was performed.
- SQLite is a single-host/single-writer design. Additional app processes must
  share the same durable database and consistent quota configuration. Multiple
  independent databases would multiply quota; shared NFS is not supported.
- Readiness checks storage and task liveness, not provider availability or worker
  progress. JSON logs support investigation; backlog-age alerts and detailed
  metrics remain deferred.
- The verifier examines records present since a timestamp. Compare its total
  against accepted creations from k6; otherwise missing records cannot be
  detected by enumerating the database alone. The historical run matched 2,706.
- The original provider check retains its documented 19/20 result: its expected
  error field differs from the provider's simulated 500 response. Neither source
  was modified. The original load test has no failure thresholds.

## Final validation

- macOS Python 3.12: **58 passed**.
- Rebuilt Linux Docker image: **58 passed**.
- Statement coverage: **420/430 = 97.67%**; branch coverage: **55/60 = 91.67%**;
  combined coverage: **96.94%**. Uncovered paths include startup cleanup, unusual
  worker failures and forced shutdown branches.
- Ruff lint and format, Compose configuration and Git whitespace checks passed.
- App image rebuilt successfully, container recreated on the existing volume,
  readiness returned 200, and a new real-provider smoke batch delivered all three
  channels. The provider and original load tests remained unchanged.
- Each code commit was checked using a temporary copy of the staged Git index,
  with the cumulative tests and Ruff run before committing. This prevents later
  untracked files from masking a broken intermediate commit.
- The official k6 run and full 2,706-record delivery verification in
  [validation.md](validation.md) predate these two cancellation fixes. They were
  reviewed, not rerun during this final audit. Final-source validation consists of
  the regression suite, Linux tests, image rebuild and real-provider smoke test.

Generated JSON, coverage output, caches and local databases are excluded from
Git. The implementation, tests, deployment configuration and documentation are
committed as separate coherent units. No existing history was rewritten.
