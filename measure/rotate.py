#!/usr/bin/env python3
"""Rotate the ExternalApiKey secret and time how long each loading path in the
API takes to see the new value.

    python measure/rotate.py                      # rotate, poll up to 15 min
    python measure/rotate.py --refresh            # then force a reference refresh
    python measure/rotate.py --restart            # then restart the web app

Needs: `az login`, the azd environment of this repo (values are read with
`azd env get-value`), and the Key Vault Secrets Officer role (Bicep grants it
to the person who ran azd). Only the Python standard library is used.
"""
import argparse
import hashlib
import json
import secrets as pysecrets
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

PATHS = ["reference", "provider", "cached", "ondemand"]


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


def status(api_url):
    with urllib.request.urlopen(f"{api_url}/api/secrets/status", timeout=30) as resp:
        return json.load(resp)


def fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def poll(api_url, expected, seen, interval, timeout_s, label):
    start = time.monotonic()
    print(f"\n[{label}] polling every {interval}s, up to {timeout_s // 60} min")
    while time.monotonic() - start < timeout_s:
        try:
            body = status(api_url)
        except Exception as ex:  # noqa: BLE001 - a restart makes the app 503 for a while
            print(f"  {int(time.monotonic() - start):4d}s  status unavailable ({type(ex).__name__})")
            time.sleep(interval)
            continue
        elapsed = int(time.monotonic() - start)
        line = [f"up={body.get('processUptimeSeconds', '?')}s"]
        for p in PATHS:
            fp = body["paths"][p]["fingerprint"]
            hit = fp == expected
            if hit and seen[p] is None:
                seen[p] = f"{label} +{elapsed}s"
            line.append(f"{p}={'NEW' if hit else 'old:' + str(fp)[:6]}")
        print(f"  {elapsed:4d}s  " + "  ".join(line))
        if all(seen[p] is not None for p in PATHS):
            return
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-url", default=None)
    ap.add_argument("--vault", default=None)
    ap.add_argument("--secret", default="ExternalApiKey")
    ap.add_argument("--interval", type=int, default=10, help="seconds between polls")
    ap.add_argument("--timeout-minutes", type=int, default=15)
    ap.add_argument("--out", default="measure/rotate-result.json", help="where to save the result")
    ap.add_argument("--refresh", action="store_true", help="after the timeout, force App Service to re-resolve Key Vault references")
    ap.add_argument("--restart", action="store_true", help="after the timeout, restart the web app")
    ap.add_argument("--nudge", action="store_true", help="after the timeout, change an app setting (the documented trigger: restart + immediate refetch of references)")
    args = ap.parse_args()

    api_url = (args.api_url or azd_value("API_URL")).rstrip("/")
    vault = args.vault or azd_value("KEY_VAULT_NAME")

    before = status(api_url)
    print(f"Process started {before.get('processStartUtc', '?')} (uptime {before.get('processUptimeSeconds', '?')} s, instance {before.get('instance', '?')})")
    print("Before rotation:")
    for p in PATHS:
        print(f"  {p:10s} {before['paths'][p]['fingerprint']}  {before['paths'][p]['note']}")

    new_value = f"rot-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{pysecrets.token_hex(8)}"
    expected = fingerprint(new_value)
    t_az = time.monotonic()
    out = run(["az", "keyvault", "secret", "set", "--vault-name", vault, "--name", args.secret,
               "--value", new_value, "--query", "id", "-o", "tsv"])
    # Stamp AFTER az returns: az.cmd startup plus the first data-plane token can
    # take tens of seconds, and the clock for "time until seen" starts when the
    # new version exists in the vault, not when we asked for it.
    rotated_at = datetime.now(timezone.utc)
    print(f"\nRotated {args.secret} at {rotated_at.isoformat()} (az took {time.monotonic() - t_az:.1f} s) -> {out}")
    print(f"Expected fingerprint: {expected}")

    seen = {p: None for p in PATHS}
    poll(api_url, expected, seen, args.interval, args.timeout_minutes * 60, "rotation")

    if args.refresh and seen["reference"] is None:
        api_name = azd_value("API_NAME")
        rg = azd_value("AZURE_RESOURCE_GROUP")
        sub = run(["az", "account", "show", "--query", "id", "-o", "tsv"])
        url = (f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/sites/"
               f"{api_name}/config/configreferences/appsettings/refresh?api-version=2022-03-01")
        # shell=True on purpose: on Windows az is az.cmd and cmd.exe splits an
        # unquoted URL at '&'; the double quotes keep it in one piece.
        if subprocess.run(f'az rest --method post --url "{url}"', shell=True).returncode != 0:
            sys.exit("az rest refresh failed")
        print("\nForced Key Vault reference refresh")
        poll(api_url, expected, seen, args.interval, 10 * 60, "refresh")

    if args.restart and seen["reference"] is None:
        api_name = azd_value("API_NAME")
        rg = azd_value("AZURE_RESOURCE_GROUP")
        run(["az", "webapp", "restart", "--name", api_name, "--resource-group", rg])
        print("\nRestarted the web app")
        poll(api_url, expected, seen, args.interval, 10 * 60, "restart")

    if args.nudge and seen["reference"] is None:
        api_name = azd_value("API_NAME")
        rg = azd_value("AZURE_RESOURCE_GROUP")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run(["az", "webapp", "config", "appsettings", "set", "--name", api_name, "--resource-group", rg,
             "--settings", f"KeyVaultReferenceNudge={stamp}", "--query", "[0].name", "-o", "tsv"])
        print(f"\nChanged app setting KeyVaultReferenceNudge={stamp} (config change => restart + refetch)")
        poll(api_url, expected, seen, args.interval, 10 * 60, "nudge")

    print("\nResult: time until each path served the rotated secret")
    print(f"  {'path':10s} {'seen':24s} source")
    for p in PATHS:
        print(f"  {p:10s} {str(seen[p] or 'not within window'):24s} {before['paths'][p]['source']}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"rotatedAtUtc": rotated_at.isoformat(), "expectedFingerprint": expected, "seen": seen,
                   "intervalSeconds": args.interval, "timeoutMinutes": args.timeout_minutes}, f, indent=2)
    print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
