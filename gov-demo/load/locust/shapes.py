"""Load profiles. The active profile can be switched at runtime (see the control route in locustfile.py)."""
import os
import time

from locust import LoadTestShape

PROFILES = ("baseline", "peak", "assistant", "none")
BASELINE_USERS = int(os.environ.get("BASELINE_USERS", "4"))
PEAK_USERS = int(os.environ.get("PEAK_USERS", "60"))
PEAK_RAMP_S = int(os.environ.get("PEAK_RAMP_S", "180"))
PEAK_HOLD_S = int(os.environ.get("PEAK_HOLD_S", "600"))
PEAK_DOWN_S = int(os.environ.get("PEAK_DOWN_S", "120"))
ASSISTANT_USERS = int(os.environ.get("ASSISTANT_USERS", "3"))

STATE = {"profile": os.environ.get("LOAD_PROFILE", "baseline"), "since": time.time()}
USER_CLASSES = {}  # profile name -> user classes, filled in by locustfile.py


def set_profile(name):
    STATE["profile"], STATE["since"] = name, time.time()


class ProfileShape(LoadTestShape):
    """Returns the user count for the active profile. Peak ramps up, holds, ramps down, then returns to baseline."""

    def tick(self):
        profile, t = STATE["profile"], time.time() - STATE["since"]
        classes = USER_CLASSES.get(profile)

        def out(users, rate):
            return (users, rate, classes) if classes else (users, rate)

        if profile == "none":
            return out(0, 1)
        if profile == "baseline":
            return out(BASELINE_USERS, 1)
        if profile == "assistant":
            return out(ASSISTANT_USERS, 1)
        if t < PEAK_RAMP_S:
            return out(max(1, int(PEAK_USERS * t / PEAK_RAMP_S)), max(1, PEAK_USERS / PEAK_RAMP_S * 2))
        if t < PEAK_RAMP_S + PEAK_HOLD_S:
            return out(PEAK_USERS, 1)
        if t < PEAK_RAMP_S + PEAK_HOLD_S + PEAK_DOWN_S:
            left = PEAK_RAMP_S + PEAK_HOLD_S + PEAK_DOWN_S - t
            return out(max(BASELINE_USERS, int(PEAK_USERS * left / PEAK_DOWN_S)), 2)
        set_profile("baseline")
        return out(BASELINE_USERS, 1)
