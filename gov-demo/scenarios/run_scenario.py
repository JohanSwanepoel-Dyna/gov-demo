#!/usr/bin/env python3
"""Apply a named scenario: reset every toggle to the defaults, then apply the scenario's overrides.
Safe to run repeatedly. Reads CONTROL_TOKEN from ../.env. Targets the k3s cluster (kubectl port-forward) by default."""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORTS = {"claims-api": 8000, "llm-gateway": 8100, "payment-worker": 8200, "legacy-stub": 8301}  # the stub's control port stays reachable when its request threads are saturated
LOCUST_PORT = 8089
# Scenario `load` values that are not Locust profiles: browser load runs separately (Playwright), Locust stays at baseline.
LOAD_TO_PROFILE = {"browser": "baseline"}


def control_token():
    for line in open(os.path.join(ROOT, ".env")):
        if line.startswith("CONTROL_TOKEN="):
            return line.split("=", 1)[1].strip()
    sys.exit("CONTROL_TOKEN not found in .env")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base, token, method, body=None):
    req = urllib.request.Request(base + "/control/toggles", method=method, headers={"X-Demo-Control": token},
                                 data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit("%s %s failed: %s %s" % (method, base, e.code, e.read().decode()))


def set_profile(base, token, profile):
    """Switch the Locust load profile. Returns the profile Locust reports, or None if it cannot be reached."""
    req = urllib.request.Request(base + "/control/profile", method="PUT", data=json.dumps({"profile": profile}).encode(),
                                 headers={"X-Demo-Control": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("profile")
    except (urllib.error.URLError, OSError) as exc:
        print("warning: could not switch the Locust profile: %s" % exc)
        return None


def normalise(value):
    """YAML turns unquoted on and off into booleans. Toggles use strings."""
    return {True: "on", False: "off"}.get(value, value) if isinstance(value, bool) else value


def desired(config, name):
    scenario = config["scenarios"][name]
    merged = {svc: dict(values) for svc, values in config["defaults"].items()}
    for svc, values in (scenario.get("toggles") or {}).items():
        merged[svc].update(values)
    return {svc: {k: normalise(v) for k, v in values.items()} for svc, values in merged.items()}, scenario


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", nargs="?")
    ap.add_argument("--target", choices=("k8s", "compose"), default="k8s")
    ap.add_argument("--namespace", default="gov-demo")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    config = yaml.safe_load(open(os.path.join(HERE, "scenarios.yaml")))
    if args.list or not args.name:
        for name, sc in config["scenarios"].items():
            print("%-18s %s" % (name, sc["description"]))
        return
    if args.name not in config["scenarios"]:
        sys.exit("unknown scenario %s, try --list" % args.name)
    want, scenario = desired(config, args.name)
    token = control_token()

    forwards, bases = [], {}
    try:
        for svc, port in PORTS.items():
            if args.target == "compose":
                bases[svc] = "http://localhost:%d" % port
                continue
            local = free_port()
            forwards.append(subprocess.Popen(
                ["kubectl", "port-forward", "-n", args.namespace, "svc/" + svc, "%d:%d" % (local, port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            bases[svc] = "http://127.0.0.1:%d" % local
        if args.target == "compose":
            bases["locust"] = "http://localhost:%d" % LOCUST_PORT
        else:
            local = free_port()
            forwards.append(subprocess.Popen(
                ["kubectl", "port-forward", "-n", args.namespace, "svc/locust", "%d:%d" % (local, LOCUST_PORT)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            bases["locust"] = "http://127.0.0.1:%d" % local
        for svc in list(PORTS) + ["locust"]:  # wait for the forwards
            for _ in range(50):
                try:
                    socket.create_connection((bases[svc].split("//")[1].split(":")[0], int(bases[svc].rsplit(":", 1)[1])), 0.2).close()
                    break
                except OSError:
                    time.sleep(0.2)
        failed = False
        for svc, values in want.items():
            call(bases[svc], token, "PUT", values)
            actual = call(bases[svc], token, "GET")
            mismatch = {k: (v, actual.get(k)) for k, v in values.items() if str(actual.get(k)) != str(v)}
            print("%-15s %s%s" % (svc, json.dumps(actual), "  MISMATCH %s" % mismatch if mismatch else ""))
            failed = failed or bool(mismatch)
        wanted = scenario.get("load", "none")
        profile = LOAD_TO_PROFILE.get(wanted, wanted)
        reported = set_profile(bases["locust"], token, profile)
        print("%-15s profile %s%s" % ("locust", reported, "" if reported == profile else "  (wanted %s)" % profile))
    finally:
        for p in forwards:
            p.terminate()
    print("scenario %s: %s" % (args.name, scenario["description"]))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
