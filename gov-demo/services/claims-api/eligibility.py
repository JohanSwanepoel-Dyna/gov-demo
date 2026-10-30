"""Fictional, deterministic eligibility rules. All thresholds and amounts are invented."""
import random
import time

MIN_AGE = 16
MAX_AGE = 70
MIN_CARING_HOURS = 20
BASE_CENTS = {"carer_payment": 25000, "carer_allowance": 13000}
INCOME_FACTOR = {"low": 1.0, "medium": 0.6}
HOURS_STEP_CENTS = 1000  # per full 10 hours above the minimum, capped at 3 steps


def evaluate(age, income_band, caring_hours, residency, risk_flag, payment_type, release="v1"):
    result = _evaluate(age, income_band, caring_hours, residency, risk_flag, payment_type)
    return _v2_bad(result, age) if release == "v2_bad" else result


def _v2_bad(result, age):
    """A bad release: slower, occasionally failing, and wrong for one age band (45 to 54)."""
    time.sleep(random.uniform(0.4, 1.2))
    if random.random() < 0.10:
        raise RuntimeError("eligibility engine v2: unexpected null in age band table")
    if 45 <= age <= 54 and result["decision"] != "ineligible":
        return {"decision": "ineligible", "reason_codes": ["INCOME_TOO_HIGH"], "amount_cents": 0}
    return result


def _evaluate(age, income_band, caring_hours, residency, risk_flag, payment_type):
    reasons = []
    if age < MIN_AGE or age > MAX_AGE:
        reasons.append("AGE_OUT_OF_BAND")
    if income_band == "high":
        reasons.append("INCOME_TOO_HIGH")
    if caring_hours < MIN_CARING_HOURS:
        reasons.append("CARING_HOURS_BELOW_MIN")
    if residency != "RESIDENT":
        reasons.append("NOT_RESIDENT")
    if reasons:
        return {"decision": "ineligible", "reason_codes": reasons, "amount_cents": 0}

    base = BASE_CENTS[payment_type] * INCOME_FACTOR[income_band]
    steps = min(3, (caring_hours - MIN_CARING_HOURS) // 10)
    amount = int(base) + steps * HOURS_STEP_CENTS
    if risk_flag:
        return {"decision": "manual_review", "reason_codes": ["RISK_FLAG_REVIEW"], "amount_cents": amount}
    return {"decision": "eligible", "reason_codes": [], "amount_cents": amount}
