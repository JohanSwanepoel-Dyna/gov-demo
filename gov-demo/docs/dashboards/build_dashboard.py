#!/usr/bin/env python3
"""Builds docs/dashboards/gov-demo.json, the Dynatrace dashboard for the demo.

  python3 docs/dashboards/build_dashboard.py            write gov-demo.json
  python3 docs/dashboards/build_dashboard.py --check    also run every tile query once with dtctl (one at a time)

Apply with: dtctl apply -f docs/dashboards/gov-demo.json
Tile queries have no timeframe of their own, they follow the dashboard timeframe.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "gov-demo.json")
DASHBOARD_ID = "fff6ca52-9dac-495c-91db-2f02b18cc977"  # makes dtctl apply update the dashboard in place
BIZ = 'fetch bizevents\n| filter event.provider == "dcs.carer-portal"'
CHAT = ('fetch spans\n| filter service.name == "claims-api" and startsWith(toString(span.name), "chat ")')
RUM_APP = "APPLICATION-EA7C4B59F27D43EB"  # Government Claim Process
# Service entities of the demo (claims-api, web, LegacyController, llm-gateway, payment-worker).
SERVICES = ["SERVICE-A07B249CEC01B91E", "SERVICE-F5D773513E6C7E59", "SERVICE-B5B342815508E1EE",
            "SERVICE-197A36756FADC0DA", "SERVICE-4896FBFBEE918D79"]
GOOD = "var(--dt-colors-charts-apdex-good-default, #1c520a)"
BAD = "var(--dt-colors-charts-loglevel-emergency-default, #ae132d)"

tiles, layouts = {}, {}
_n = [0]


def add(tile, x, y, w, h):
    key = str(_n[0])
    _n[0] += 1
    tiles[key] = tile
    layouts[key] = {"x": x, "y": y, "w": w, "h": h}


def md(text, x, y, w, h):
    add({"type": "markdown", "content": text}, x, y, w, h)


def rule(value, color):
    return {"field": "DT.name", "type": "string", "comparator": "= *value*", "value": value,
            "colorMode": "single-color", "color": color}


def data(title, query, viz, settings=None, x=0, y=0, w=6, h=6):
    vs = {"autoSelectVisualization": False}
    vs.update(settings or {})
    add({"title": title, "type": "data", "query": query, "visualization": viz, "visualizationSettings": vs,
         "querySettings": {"maxResultRecords": 1000, "defaultScanLimitGbytes": 500, "maxResultMegaBytes": 100,
                           "defaultSamplingRatio": 10, "enableSampling": False}}, x, y, w, h)


def stat(title, query, field, label, x):
    data(title, query, "singleValue", {"singleValue": {"label": label, "recordField": field}}, x=x, y=2, w=4, h=4)


def lines(title, query, x, y, w, h=7, rules=None, viz="lineChart"):
    cs = {"chartSettings": {"legend": {"position": "bottom"}}}
    if rules:
        cs["coloring"] = {"colorRules": rules}
    data(title, query, viz, cs, x=x, y=y, w=w, h=h)


def bars(title, query, x, y, w, h=7, palette="purple-rain"):
    data(title, query, "categoricalBarChart",
         {"chartSettings": {"legend": {"position": "bottom"}},
          "coloring": {"colorRules": [{"colorMode": "color-palette", "colorPalette": palette, "comparator": "= *value*",
                                       "field": "DT.name", "type": "string", "value": ""}]}}, x=x, y=y, w=w, h=h)


def table(title, query, x, y, w, h=7):
    data(title, query, "table", {"table": {}}, x=x, y=y, w=w, h=h)


md("# Carer Support Portal (fictional demonstration)\n"
   "Department of Community Services demo. All policy, amounts and citizens are invented. "
   "Run scenarios with `make scenario NAME=...`, see `docs/runbook.md`.", 0, 0, 24, 2)

# Headline numbers
stat("Claims submitted", BIZ + '\n| filter event.type == "claim.submitted"\n| summarize submitted = count()',
     "submitted", "Submitted", 0)
stat("Payments posted", BIZ + '\n| filter event.type == "claim.payment_posted"\n| summarize posted = count()',
     "posted", "Paid", 4)
stat("Payments failed", BIZ + '\n| filter event.type == "claim.payment_failed"\n| summarize failed = count()',
     "failed", "Failed", 8)
stat("Average queue wait (ms)", BIZ + '\n| filter event.type == "claim.payment_posted"\n| summarize wait = avg(queue_wait_ms)',
     "wait", "Queue wait ms", 12)
stat("Tokens used", "timeseries tokens = sum(gen_ai.client.token.usage)\n| fieldsAdd total = arraySum(tokens)\n| fields total",
     "total", "Tokens", 16)
stat("Prompts blocked by guardrails",
     CHAT + '\n| summarize blocked = countIf(matchesPhrase(toString(gen_ai.response.finish_reasons), "content_filter"))',
     "blocked", "Blocked", 20)

# Claims and payments
md("## Claims and payments", 0, 6, 24, 1)
bars("Claim journey, events by step",
     BIZ + "\n| summarize events = count(), by: {event.type}\n| sort events desc", 0, 7, 8)
lines("Claims over time",
      BIZ + '\n| filter in(event.type, "claim.submitted", "claim.payment_posted", "claim.payment_failed")\n'
            "| makeTimeseries events = count(), by: {event.type}", 8, 7, 16,
      rules=[rule("claim.payment_posted", GOOD), rule("claim.payment_failed", BAD)])
lines("Payment queue wait (ms)",
      BIZ + '\n| filter event.type == "claim.payment_posted"\n'
            "| makeTimeseries average = avg(queue_wait_ms), p95 = percentile(queue_wait_ms, 95)", 0, 14, 10)
bars("Failed payments by error",
     BIZ + '\n| filter event.type == "claim.payment_failed"\n| summarize failed = count(), by: {error}', 10, 14, 6, palette="fireplace")
lines("Server response time p95 by service",
      'fetch spans\n| filter k8s.namespace.name == "gov-demo" and span.kind == "server"\n'
      "| makeTimeseries p95 = percentile(duration, 95), by: {dt.service.name}", 16, 14, 8)

# AI assistant
md("## AI assistant", 0, 21, 24, 1)
lines("Tokens by type", "timeseries tokens = sum(gen_ai.client.token.usage), by: {gen_ai.token.type}", 0, 22, 8, viz="areaChart")
lines("Chat completion latency", CHAT + "\n| makeTimeseries p50 = percentile(duration, 50), p95 = percentile(duration, 95)", 8, 22, 8)
bars("Guardrail outcome per chat",
     CHAT + '\n| fieldsAdd outcome = if(matchesPhrase(toString(gen_ai.response.finish_reasons), "content_filter"), "blocked", else: "allowed")\n'
            "| summarize chats = count(), by: {outcome}", 16, 22, 4)
bars("Chat errors by type", CHAT + "\n| filter isNotNull(error.type)\n| summarize failed = count(), by: {error.type}", 20, 22, 4,
     palette="fireplace")

# Experience and change
md("## Experience and change", 0, 29, 24, 1)
bars("RUM funnel, sessions per step",
     f'fetch user.events\n| filter dt.rum.application.entity == "{RUM_APP}" and characteristics.has_view_summary == true\n'
     "| summarize sessions = countDistinct(dt.rum.session.id), by: {view.detected_name}\n| sort sessions desc", 0, 30, 8)
table("Deployment events",
      'fetch events\n| filter event.type == "CUSTOM_DEPLOYMENT"\n'
      "| fields timestamp, event.name, event.description\n| sort timestamp desc\n| limit 10", 8, 30, 8)
ids = " or ".join(f'contains(toString(affected_entity_ids), "{i}")' for i in SERVICES)
table("Problems on the demo services",
      f"fetch dt.davis.problems\n| filter {ids}\n| fields timestamp, display_id, event.name, event.status\n| sort timestamp desc\n| limit 10",
      16, 30, 8)

dashboard = {"version": 21, "variables": [], "tiles": tiles, "layouts": layouts, "annotations": [], "settings": {},
             "importedWithCode": False}
document = {"id": DASHBOARD_ID, "name": "Carer Support Portal demo", "type": "dashboard", "content": dashboard}
with open(OUT, "w") as f:
    json.dump(document, f, indent=1)
print(f"wrote {OUT} with {sum(t['type'] == 'data' for t in tiles.values())} data tiles")

if "--check" in sys.argv:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=2)
    bad = 0
    for key, t in tiles.items():
        if t["type"] != "data":
            continue
        r = subprocess.run(["dtctl", "query", t["query"], "-o", "json",
                            "--default-timeframe-start", start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "--default-timeframe-end", end.strftime("%Y-%m-%dT%H:%M:%SZ")],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
            res = d.get("result", d)
            rows = res.get("records", res) if isinstance(res, dict) else res
            ok = isinstance(rows, list)
            note = f"{len(rows)} rows" if ok else "ERROR " + json.dumps(d.get("error", d))[:180]
        except Exception:
            ok, note = False, "ERROR " + (r.stdout or r.stderr)[:180].replace("\n", " ")
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {t['title'][:42]:42} {note}")
    sys.exit(1 if bad else 0)
