# Browser load (Playwright)

Real browser sessions for RUM: funnel drop-off, Session Replay, frontend to backend traces. Run on demand, not part of the standing stack. Protocol load is in `../locust`.

```
make browser-load PROFILE=completer SESSIONS=5
make browser-load PROFILE=abandoner SESSIONS=5 CONCURRENCY=2
make browser-load PROFILE=assistant SESSIONS=3
```

| Option | Default | Purpose |
|---|---|---|
| `--base-url` or `BASE_URL` | http://localhost:8080 | Where the portal is reachable. On k3s use `kubectl port-forward -n gov-demo svc/web 8080:8080` |
| `--profile` | completer | `completer`: full journey to paid. `abandoner`: leaves at the upload step. `assistant`: opens the widget and clicks two prompts |
| `--sessions` | 3 | Number of sessions. Each one is a fresh browser context, so RUM records a new session |
| `--concurrency` | 3 | Sessions at the same time |
| `--credentials` | ../../db/out/credentials.csv | Seed credentials. Citizens whose id divides by 20 are skipped (always ineligible) |
| `--headed` | off | Show the browser |
| `--bundled` | off | Use Playwright's own Chromium (needs `npx playwright install chromium`, about 170 MB) instead of the installed Google Chrome |

It uses `playwright-core` and the installed Chrome, so nothing large is downloaded. The exit code is non-zero if a session errors or times out.
