# Agentic development with Dynatrace: alert, diagnosis, fix, proof

A ten to twelve minute live story. A bad release of the eligibility engine goes out. An AI coding agent investigates using only what Dynatrace shows, finds the defect in the code, fixes it, redeploys, and proves the fix in the same data. Fictional agency, synthetic data, lab cluster only.

The point to make: the agent does not guess. Every step is a question put to Dynatrace (problems, deployment events, traces, logs), and the answer is checked in Dynatrace again afterwards.

## The defect

Release 2 of the eligibility engine (`services/claims-api/eligibility.py`) has two real code problems:

| Problem | What Dynatrace shows | Fix |
|---|---|---|
| The age band rate schedule has no band for ages 45 to 54 | `TypeError: unsupported operand type(s) for *: 'int' and 'NoneType'` on the eligibility span, with a stack trace that names `_evaluate_v2`, line 38. About 28 percent of checks fail | Add the missing `(45, 54, 1.0)` band |
| The schedule is read on every check (a policy service round trip) | A child span `policy.load_rate_schedule`, 787 ms on average (max 1,191 ms), which sets eligibility latency | Cache the schedule |

The code does not say "bug" anywhere. The release flag is `eligibility_release` (`v1` or `v2`).

## Before you start

1. `kubectl config current-context` is the cluster that runs the demo (`rancher-desktop` here).
2. `dtctl` is logged in. Run one `dtctl` call at a time; parallel calls invalidate the login.
3. The stack has been on baseline for at least 10 minutes, so the "before" is healthy. `make demo-status` should say release `v1` and the engine file as committed.
4. `git status` is clean for `services/claims-api/eligibility.py` (the helper restores it from git).
5. Open in the browser: the dashboard "Carer Support Portal demo", and a claims-api service view.

## The story

| Step | Time | You do | Show |
|---|---|---|---|
| 1. Release | 1 min | `make demo-arm` (rebuilds `claims-api`, switches to release v2, steady load) | A "release v2" deployment event on `claims-api` 1 to 2 minutes later |
| 2. Wait for data | at least 5 min | Talk about the setup | Data lags the action by 2 to 4 minutes. Start the agent no sooner than 5 minutes after arming (see the cold test below) |
| 3. Hand over | 1 min | Give the agent the prompt below | |
| 4. Investigate | 3 to 4 min | Watch the agent work | Problems, then the failure step at the release, then the exception and stack trace |
| 5. Fix | 1 min | The agent edits `eligibility.py` | A two line diff |
| 6. Redeploy | 1 min | The agent runs `make demo-redeploy` | |
| 7. Proof | 3 to 4 min | The agent queries again | Failures back to 0 and latency back to about 115 ms |
| 8. Reset | 1 min | `make demo-reset` after the demo | |

### The prompt

> Eligibility checks on the Carer Support Portal started failing and slowing down a few minutes ago. Use Dynatrace (dtctl, one call at a time) to find out what changed and why, then fix it in `gov_app/gov-demo`, redeploy with `make demo-redeploy`, and prove in Dynatrace that the fix worked. Do not change anything in the Dynatrace tenant.

### What a good investigation finds (queries run on 2026-11-11, all return data)

1. What changed: `fetch events, from:now()-1h | filter event.type == "CUSTOM_DEPLOYMENT" | fields timestamp, event.name, event.description, deployment.version, deployment.previous_version` shows "eligibility-engine release v2", from v1 to v2. (There is no `service.name` or `title` field on these events, the service is in `dt.source_entity`.)
2. When it went wrong, per minute:
   ```
   fetch spans, from:now()-14m
   | filter service.name == "claims-api" and span.kind == "server" and http.route == "/api/claims/{claim_id}/eligibility"
   | summarize requests=count(), failed=countIf(request.is_failed == true), avg_ms=avg(duration)/1000000, by:{minute=bin(start_time, 1m)}
   | sort minute asc
   ```
   Before the release: about 115 to 135 ms and 0 failures. After: 660 to 755 ms and 9 to 17 failures a minute out of 44 to 50 checks.
3. Why it fails: failed server spans have no `http.response.status_code`, so look at `span.events` (`fieldsAdd ev = toString(span.events)`). A failed server span carries the exception there (type `TypeError`, message and stack trace, last application frame `/app/eligibility.py`, line 38, `_evaluate_v2`). The same traceback is in the logs (`contains(content, "NoneType")`).
4. Why it is slow: `fetch spans | filter span.name == "policy.load_rate_schedule" | summarize avg(duration)/1000000` gives 787 ms on average.
5. Davis opened problems on its own: a "Failure rate increase" on `claims-api` one minute after the release, a "Response time degradation" four minutes after, and a failure rate problem on `web` with the known root cause placeholder "Requests to unmonitored hosts". See the caveats.

### The proof (rehearsal on 2026-11-11, redeploy at 03:52 UTC)

| Minutes | Average ms | Failed per minute |
|---|---|---|
| Before the release (03:43 to 03:44) | 116 to 133 | 0 |
| Release v2 (03:45 to 03:51) | 660 to 755 | 9 to 17 |
| Redeploy minute (03:52) | 418 | 8 |
| After the fix (03:53 onward) | 112 to 118 | 0 |

A citizen aged 45 to 54 (citizen 4) went from HTTP 500 to HTTP 200 in 0.15 s.

## Cold test (2026-11-11)

A fresh agent got the exact prompt above, with no access to this run sheet, the progress log or the scenario files. It found the right defect, made an equivalent fix (the missing `(45, 54, 1.0)` band and a cache for the schedule), redeployed with `make demo-redeploy` and showed zero failures afterwards. It took about 15 minutes, 6 of them waiting for data. I checked its numbers against Dynatrace myself and they match.

What the test showed about the demo:

- **It started too early.** The agent began about a minute after arming, so there was almost no data from the new run. Its "during" figures came from my earlier rehearsal, and its fix went in about two minutes after arming. The proof compared the fix against that earlier incident, not against the run it was fixing. Wait at least 5 minutes after arming.
- **It did not find the exception in Dynatrace.** Failed spans have no status code, so it read the code and matched the 45 to 54 pattern instead. The exception and stack trace are on the span (`span.events`), which is now in the list above. If you want the agent to find it unaided, say so in the prompt or have it look at span events.
- **Deployment events looked empty** until it dumped the JSON, because the fields it chose do not exist. The query above lists the ones that do.
- **Several "release v2" events and re-arms** from repeated runs confused the timeline (it could not tell whether v2 stayed on). Reset and wait before a real showing so there is one clear release marker.
- **Log search was noisy once.** It reported a flood of OpenTelemetry exporter timeouts in the ERROR logs. I could not reproduce that (no exporter errors in the last hour), so treat it as seen once and unexplained.

## Reset and repeat

`make demo-reset` restores `eligibility.py` from git (it shows what it discards and asks first, `YES=yes` skips the question), rebuilds `claims-api`, and returns to release v1 and baseline load. Wait about 10 minutes before the next run so the "before" is healthy again.

Commit nothing from a demo run. If you want to keep the agent's fix, commit it on a branch before `make demo-reset`.

## Caveats

- Restarting `claims-api` resets toggles, so `make demo-redeploy` switches release v2 back on after the rebuild. That logs a second deployment event with the same name, "release v2". The timestamps tell the two apart.
- Dynatrace data lags by 2 to 4 minutes, so an agent that checks too early will see nothing. Say so in the prompt or let it wait.
- Davis problems are real but not reliable: they were raised this time within one to five minutes, but the `web` problem points at "Requests to unmonitored hosts" and the earlier tuning decision was to leave Davis alone. Treat the SLOs and the span data as the evidence, and the problems as a bonus. The feed also holds older unrelated problems on the cluster.
- The slow schedule read is a sleep that stands in for a network call (the code comment says so). A reader of the code will notice it.
- Rehearsed by the author knowing the answer, not by an agent run cold. Run it once yourself first.
- `make demo-arm` and `make demo-reset` run `git checkout` on the engine file. Commit or stash any real change to that file first.
