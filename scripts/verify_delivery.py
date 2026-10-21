"""Verify a load-test batch reaches provider-confirmed terminal states.

Uses read-only SQLite snapshots inside the Compose app container, then checks
every request through the public API. Requires only the Python standard library.
"""

import argparse
import json
import subprocess
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SNAPSHOT = """
import json, os, sqlite3, sys
from pathlib import Path
path = Path(os.environ['NOTIFY_DATABASE_PATH']).resolve()
with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
    db.row_factory = sqlite3.Row
    rows = db.execute('''SELECT id, status, attempts, provider_id, last_error,
                        created_at, updated_at, lease_expires_at
                        FROM notifications WHERE created_at >= ? ORDER BY created_at''',
                      (float(sys.argv[1]),)).fetchall()
    print(json.dumps([dict(row) for row in rows]))
"""


def snapshot(compose: list[str], since: float) -> list[dict]:
    result = subprocess.run(
        [*compose, "exec", "-T", "app", "python", "-c", SNAPSHOT, str(since)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=float, required=True, help="Batch start, Unix seconds")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--compose-file", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    compose = ["docker", "compose"]
    for filename in args.compose_file:
        compose.extend(["-f", filename])
    deadline = time.monotonic() + args.timeout
    while True:
        rows = snapshot(compose, args.since)
        states = Counter(row["status"] for row in rows)
        print(
            json.dumps({"timestamp": time.time(), "total": len(rows), "states": states}), flush=True
        )
        if not rows:
            raise RuntimeError("No requests found for this batch; refusing an empty success")
        if states["queued"] + states["processing"] == 0 or time.monotonic() >= deadline:
            break
        time.sleep(args.interval)

    def check_api(row: dict) -> bool:
        url = args.base_url.rstrip("/") + "/v1/requests/" + row["id"]
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200 and json.load(response) == {
                "id": row["id"],
                "status": row["status"],
            }

    with ThreadPoolExecutor(max_workers=8) as executor:
        api_checks = list(executor.map(check_api, rows))
    confirmed = sum(row["status"] == "sent" and bool(row["provider_id"]) for row in rows)
    report = {
        "batch_since": args.since,
        "verified_at": time.time(),
        "total": len(rows),
        "states": dict(states),
        "provider_confirmed_sent": confirmed,
        "total_attempts": sum(row["attempts"] for row in rows),
        "attempt_histogram": dict(Counter(row["attempts"] for row in rows)),
        "api_checks_passed": sum(api_checks),
        "last_terminal_update": max(row["updated_at"] for row in rows),
        "first_created_at": min(row["created_at"] for row in rows),
        "processing_span_seconds": max(row["updated_at"] for row in rows)
        - min(row["created_at"] for row in rows),
        "failed_requests": [
            {"id": row["id"], "error": row["last_error"]}
            for row in rows
            if row["status"] == "failed"
        ],
    }
    report["passed"] = confirmed == len(rows) and all(api_checks)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
