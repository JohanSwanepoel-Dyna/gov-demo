"""Eligibility assessment shared by the claim form and the assistant tool."""
from datetime import date

import eligibility
import legacy
import toggles
from db import connect


class LegacyUnavailable(Exception):
    pass


def assess(citizen_id, payment_type, income_band, caring_hours):
    """Looks up the citizen and the legacy customer record, then applies the rules. Raises LegacyUnavailable if legacy fails."""
    with connect() as conn:
        citizen = conn.execute("SELECT dob, risk_flag FROM citizens WHERE id=%s", (citizen_id,)).fetchone()
    try:
        customer = legacy.lookup_customer(citizen_id)
    except Exception as exc:
        raise LegacyUnavailable(str(exc)) from exc
    today, dob = date.today(), citizen["dob"]
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return eligibility.evaluate(age, income_band, caring_hours, customer["residency"], citizen["risk_flag"], payment_type,
                              toggles.STATE["eligibility_release"])
