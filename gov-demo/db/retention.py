"""Delete demo data older than RETENTION_HOURS so the database stays small under constant load.
Keeps the seeded citizens. Run once (CronJob) or with --loop SECONDS (Compose)."""
import argparse
import os
import time

import psycopg

DSN = os.environ["DATABASE_URL"]
# Child tables first because of the foreign keys.
SUB = "SELECT id FROM claims WHERE created_at < %(cutoff)s"
# (table, rows to delete). Child tables first because of the foreign keys.
STEPS = [
    ("payments", f"FROM payments WHERE claim_id IN ({SUB})"),
    ("payment_queue", f"FROM payment_queue WHERE claim_id IN ({SUB})"),
    ("documents", f"FROM documents WHERE claim_id IN ({SUB})"),
    ("claims", "FROM claims WHERE created_at < %(cutoff)s"),
]


def prune(hours, dry_run):
    with psycopg.connect(DSN) as conn:
        cutoff = conn.execute("SELECT now() - make_interval(secs => %s)", (hours * 3600,)).fetchone()[0]
        counts = {}
        for table, rest in STEPS:
            if dry_run:
                counts[table] = conn.execute("SELECT count(*) " + rest, {"cutoff": cutoff}).fetchone()[0]
            else:
                counts[table] = conn.execute("DELETE " + rest, {"cutoff": cutoff}).rowcount
        if dry_run:
            conn.rollback()
    print(("would delete " if dry_run else "deleted ") + ", ".join(f"{n} {t}" for t, n in counts.items())
          + f" older than {hours} hours", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=float(os.environ.get("RETENTION_HOURS", "6")))
    ap.add_argument("--loop", type=int, default=0, help="repeat every N seconds")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    while True:
        prune(args.hours, args.dry_run)
        if not args.loop:
            return
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
