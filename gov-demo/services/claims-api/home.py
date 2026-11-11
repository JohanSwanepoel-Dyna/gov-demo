"""Data for the DynaGov home page: the citizen's name and inbox.
Notices from other agencies are synthetic. Notices about carer claims come from the claims table."""
from datetime import date, datetime, timedelta, timezone

# (days ago, sender, subject)
NOTICES = [
    (1, "Revenue Office", "Notice of assessment available"),
    (3, "Health Records", "Your health summary was updated"),
    (6, "Housing Assistance", "Rent assistance review due next month"),
    (9, "DynaGov", "Welcome to DynaGov"),
    (14, "Digital Licence", "Your licence renews in 60 days"),
    (21, "Revenue Office", "Payment summary ready to view"),
]
CLAIM_SUBJECTS = {
    "submitted": "We received your claim {ref}",
    "paid": "Payment for claim {ref} has been processed",
    "failed": "Payment for claim {ref} failed, please contact the department",
}
INBOX_LIMIT = 10


def build_home(conn, citizen_id):
    citizen = conn.execute("SELECT name FROM citizens WHERE id=%s", (citizen_id,)).fetchone()
    claims = conn.execute(
        "SELECT id, status, reference, COALESCE(submitted_at, created_at) AS at FROM claims "
        "WHERE citizen_id=%s AND reference IS NOT NULL ORDER BY at DESC LIMIT 5", (citizen_id,)).fetchall()
    today, now = date.today(), datetime.now(timezone.utc)
    messages = [{"id": f"notice-{days}", "sender": sender, "subject": subject,
                 "date": (today - timedelta(days=days)).isoformat(), "unread": days <= 6}
                for days, sender, subject in NOTICES]
    for claim in claims:
        if claim["status"] in CLAIM_SUBJECTS:
            messages.append({"id": str(claim["id"]), "sender": "Carer Support",
                             "subject": CLAIM_SUBJECTS[claim["status"]].format(ref=claim["reference"]),
                             "date": claim["at"].date().isoformat(), "unread": now - claim["at"] < timedelta(days=1)})
    messages.sort(key=lambda m: m["date"], reverse=True)
    messages = messages[:INBOX_LIMIT]
    return {"name": citizen["name"], "unread": sum(m["unread"] for m in messages), "messages": messages}
