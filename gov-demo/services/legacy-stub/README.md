# legacy-stub

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | 8300 | Listen port |
| `TOMCAT_MAX_THREADS` | 8 | Tomcat worker threads |
| `TOMCAT_ACCEPT_COUNT` | 50 | Tomcat accept queue length |
| `HEALTH_PORT` | 8301 | Port for `GET /healthz` and the toggle API, served on their own threads so health probes and scenario resets still work when every Tomcat worker is busy. Both are also available on the main port |
| `JAVA_OPTS` | `-Xmx384m` | JVM options |
| `MODE` | normal | Initial `mode` toggle (normal, slow, brownout) |
| `CONTROL_TOKEN` | none | Shared secret for the toggle API, sent as header `X-Demo-Control`. The API is disabled when unset |
| `LATENCY_MIN_MS` | 50 | Minimum added latency per call |
| `LATENCY_MAX_MS` | 150 | Maximum added latency per call |

## Toggle API

`GET` and `PUT /control/toggles` with header `X-Demo-Control`, on port 8301 (use this one, it survives saturation) and on 8300. State is in memory and resets on restart.

| Toggle | Values | Effect |
|---|---|---|
| `mode` | normal, slow, brownout | normal: 50 to 150 ms. slow: 2 to 5 s. brownout: slow plus 15% HTTP 500 |
| `pool_threads` | 1 to 64 | Resizes the Tomcat worker pool at runtime |
