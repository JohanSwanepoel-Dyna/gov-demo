"""In-memory toggle state and the shared-secret check. State resets on restart, defaults come from env."""
import hmac
import os

from fastapi import Header, HTTPException

# name -> (default, allowed values). Allowed is a tuple of strings or a range of integers.
# The env var is the upper-cased name.
SPEC = {
    "latency": ("normal", ("normal", "slow")),
    "provider_errors": ("none", ("none", "429", "503")),
    "provider_error_rate": ("30", range(0, 101)),
    "guardrails": ("on", ("on", "off")),
    "response_mode": ("grounded", ("grounded", "hallucinated", "verbose")),
}
STATE = {name: os.environ.get(name.upper(), default) for name, (default, _) in SPEC.items()}


async def require_control(x_demo_control: str | None = Header(default=None)):
    token = os.environ.get("CONTROL_TOKEN")
    if not token:
        raise HTTPException(503, "control API disabled: CONTROL_TOKEN not set")
    if not x_demo_control or not hmac.compare_digest(x_demo_control, token):
        raise HTTPException(401, "bad control token")


def valid(allowed, value):
    if isinstance(allowed, range):
        return value.isdigit() and int(value) in allowed
    return value in allowed


def update(changes):
    changes = {name: str(value) for name, value in changes.items()}
    for name, value in changes.items():
        if name not in SPEC:
            raise HTTPException(422, f"unknown toggle {name}")
        if not valid(SPEC[name][1], value):
            raise HTTPException(422, f"{name} must be one of {SPEC[name][1] if not isinstance(SPEC[name][1], range) else '0 to 100'}")
    STATE.update(changes)
    return STATE
