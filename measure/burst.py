#!/usr/bin/env python3
"""Send N requests to one secret path and record the time window, so the Key
Vault audit log can show how many SecretGet calls that path really made.

    python measure/burst.py --path ondemand --count 200
    python measure/burst.py --path cached   --count 200
    python measure/burst.py --path provider --count 200

Then, once Log Analytics has ingested the events (a few minutes), run the
query the script prints, or:

    python measure/burst.py --path ondemand --count 200 --query

which runs it for you with `az monitor log-analytics query`.
"""
import argparse
import concurrent.futures
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone


def run(cmd):
    exe = shutil.which(cmd[0])
    if exe is None:
        sys.exit(f"{cmd[0]} not found on PATH")
    result = subprocess.run([exe] + cmd[1:], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed:\n{result.stderr}")
    return result.stdout.strip()


def azd_value(name):
    return run(["azd", "env", "get-value", name])


def hit(url):
    t = time.monotonic()
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = json.load(resp)
    return (time.monotonic() - t) * 1000, body.get("keyVaultCallMs", 0)


KQL = """AzureDiagnostics
| where ResourceProvider == "MICROSOFT.KEYVAULT" and OperationName == "SecretGet"
| where TimeGenerated between (datetime({start}) .. datetime({end}))
| summarize calls = count(), throttled = countif(ResultSignature == "Too Many Requests")
    by identity_claim_appid_g, ResultSignature
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-url", default=None)
    ap.add_argument("--path", choices=["reference", "provider", "cached", "ondemand"], required=True)
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--query", action="store_true", help="wait and run the audit query against Log Analytics")
    ap.add_argument("--wait-minutes", type=int, default=5, help="ingestion delay to wait before --query")
    args = ap.parse_args()

    api_url = (args.api_url or azd_value("API_URL")).rstrip("/")
    url = f"{api_url}/api/secrets/{args.path}"

    start = datetime.now(timezone.utc) - timedelta(seconds=5)
    latencies, kv_ms = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for lat, kv in pool.map(lambda _: hit(url), range(args.count)):
            latencies.append(lat)
            kv_ms.append(kv)
    end = datetime.now(timezone.utc) + timedelta(seconds=5)

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    vault_calls_reported = sum(1 for v in kv_ms if v > 0)
    print(f"{args.count} requests to /api/secrets/{args.path} with concurrency {args.concurrency}")
    print(f"  latency p50 {p50:.0f} ms, p95 {p95:.0f} ms")
    print(f"  requests that reported a Key Vault call: {vault_calls_reported}")
    print(f"  window: {start.isoformat()} .. {end.isoformat()}")

    kql = KQL.format(start=start.strftime("%Y-%m-%dT%H:%M:%SZ"), end=end.strftime("%Y-%m-%dT%H:%M:%SZ"))
    print("\nAudit query (Log Analytics):\n" + kql)

    result = {"path": args.path, "count": args.count, "concurrency": args.concurrency, "p50Ms": p50, "p95Ms": p95,
              "reportedVaultCalls": vault_calls_reported, "windowStart": start.isoformat(), "windowEnd": end.isoformat()}

    if args.query:
        workspace = azd_value("LOG_ANALYTICS_WORKSPACE_ID")
        print(f"Waiting {args.wait_minutes} min for ingestion...")
        time.sleep(args.wait_minutes * 60)
        one_line = " ".join(line.strip() for line in kql.splitlines() if line.strip())
        out = run(["az", "monitor", "log-analytics", "query", "-w", workspace, "--analytics-query", one_line, "-o", "json"])
        rows = json.loads(out)
        print("Audit log says:")
        for r in rows:
            print(f"  appid {r.get('identity_claim_appid_g')}  {r.get('ResultSignature')}  calls={r.get('calls')}  throttled={r.get('throttled')}")
        result["audit"] = rows

    with open(f"measure/burst-{args.path}.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved measure/burst-{args.path}.json")


if __name__ == "__main__":
    main()
