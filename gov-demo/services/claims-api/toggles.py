"""In-memory toggle state and the shared-secret check. State resets on restart, defaults come from env."""
import hmac
import os

from fastapi import Header, HTTPException

# name -> (default, allowed values). Allowed is a tuple of strings or a range of integers.
# The env var is the upper-cased name.
SPEC = {
    "capture_content": ("on", ("on", "off")),
    "eligibility_release": ("v1", ("v1", "v2")),
    "upload_fault": ("none", ("none", "slow", "error")),
    "log_pii": ("off", ("on", "off")),
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
            raise HTTPException(422, f"{name} must be one of {', '.join(SPEC[name][1])}")
    STATE.update(changes)
    return STATE
