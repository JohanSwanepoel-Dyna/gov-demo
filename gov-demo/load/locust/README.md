# Locust

Protocol-level load for the portal through `web`. Browser load is in `../browser`.

| Variable | Default | Purpose |
|---|---|---|
| `LOAD_PROFILE` | baseline | Profile at start: baseline, peak, assistant or none |
| `CREDENTIALS_CSV` | /data/credentials.csv | Seed credentials (citizen_id, passcode) |
| `CONTROL_TOKEN` | none | Secret for `GET/PUT /control/profile` (header `X-Demo-Control`). Disabled when unset |
| `BASELINE_USERS` | 4 | Users in the baseline profile |
| `PEAK_USERS` | 60 | Users at the top of the peak profile |
| `PEAK_RAMP_S`, `PEAK_HOLD_S`, `PEAK_DOWN_S` | 180, 600, 120 | Peak ramp up, hold and ramp down in seconds. After the ramp down the profile returns to baseline |
| `ASSISTANT_USERS` | 3 | Users in the assistant profile |

User classes: Completer (weight 5, full claim to paid), Abandoner (2, stops before the upload), AssistantUser (2, cycles an eligibility question, a general question, an injection attempt, a prompt with a TFN, and a long-answer request). Think time is 1 to 4 s. Request names are fixed, with ids shown as `[id]`, so Locust stats line up with Dynatrace.

User counts are starting assumptions. Adjust after the first run on the lab node.
