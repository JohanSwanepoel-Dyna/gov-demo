"""Seed 500 synthetic citizens and write a credentials CSV. Idempotent.

  python seed.py                      seed the database (DATABASE_URL) and write the CSV
  python seed.py --csv-only [--out F] write only the credentials CSV, no database needed (same numbers every time)
"""
import csv
import hashlib
import os
import random
import sys
import time
from datetime import date, timedelta

COUNT = int(os.environ.get("SEED_COUNT", "500"))
OUT = os.environ.get("CREDENTIALS_CSV", "/out/credentials.csv")
DSN = os.environ.get("DATABASE_URL")

FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Quinn",
         "Noor", "Priya", "Mei", "Tane", "Aroha", "Luca", "Sofia", "Omar", "Layla", "Kofi"]
LAST = ["Nguyen", "Smith", "Patel", "Williams", "Brown", "Wilson", "Taylor", "Anderson", "Kaur", "Singh",
        "Murray", "Campbell", "Hughes", "Fraser", "Costa", "Rossi", "Khan", "Lee", "Walker", "Evans"]
STREET = ["Wattle", "Banksia", "Eucalypt", "Acacia", "Grevillea", "Boronia", "Casuarina", "Waratah"]
SUFFIX = ["St", "Rd", "Ave", "Cres", "Pl"]
TOWN = [("Rivertown", "NSW", 2999), ("Hillcrest", "VIC", 3999), ("Baytown", "QLD", 4999),
        ("Dunmore", "SA", 5999), ("Karrin", "WA", 6999), ("Tamar Vale", "TAS", 7999)]


def make_tfn(rng):
    # 9 digits, weighted checksum mod 11 (format-valid, not tied to a real person).
    w = [1, 4, 3, 7, 5, 8, 6, 9, 10]
    while True:
        d = [rng.randint(0, 9) for _ in range(8)]
        for last in range(10):
            full = d + [last]
            if sum(a * b for a, b in zip(full, w)) % 11 == 0 and full[0] != 0:
                return "".join(map(str, full))


def make_medicare(rng):
    # 8 digits (first 2-6), check digit, issue number: 10 digits.
    w = [1, 3, 7, 9, 1, 3, 7, 9]
    d = [rng.randint(2, 6)] + [rng.randint(0, 9) for _ in range(7)]
    check = sum(a * b for a, b in zip(d, w)) % 10
    return "".join(map(str, d)) + str(check) + str(rng.randint(1, 9))


def connect():
    import psycopg  # only needed when seeding the database
    if not DSN:
        sys.exit("DATABASE_URL is not set")
    for attempt in range(30):
        try:
            return psycopg.connect(DSN)
        except psycopg.OperationalError:
            print(f"waiting for postgres ({attempt + 1}/30)")
            time.sleep(2)
    sys.exit("postgres not reachable")


def write_csv(creds):
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["citizen_id", "passcode"])
        w.writerows(creds)
    print(f"wrote {OUT}")


def main():
    rng = random.Random(42)
    rows, creds = [], []
    for cid in range(1, COUNT + 1):
        dob = date(1950, 1, 1) + timedelta(days=rng.randint(0, 365 * 55))
        town, state, pc = rng.choice(TOWN)
        addr = f"{rng.randint(1, 250)} {rng.choice(STREET)} {rng.choice(SUFFIX)}, {town} {state} {pc}"
        passcode = f"{rng.randint(0, 999999):06d}"
        rows.append((cid, f"{rng.choice(FIRST)} {rng.choice(LAST)}", dob, make_tfn(rng), make_medicare(rng),
                     rng.randint(1, 5), addr, rng.random() < 0.05,
                     hashlib.sha256(passcode.encode()).hexdigest()))
        creds.append((cid, passcode))

    if "--out" in sys.argv:
        global OUT
        OUT = sys.argv[sys.argv.index("--out") + 1]
    if "--csv-only" in sys.argv:
        write_csv(creds)
        return

    with connect() as conn:
        if conn.execute("SELECT to_regclass('citizens')").fetchone()[0] is None:
            conn.execute(open(os.path.join(os.path.dirname(__file__), "schema.sql")).read())
            print("applied schema.sql")
        n = conn.execute("SELECT count(*) FROM citizens").fetchone()[0]
        if n == 0:
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO citizens VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
            print(f"seeded {len(rows)} citizens")
        elif n == COUNT:
            print(f"citizens already seeded ({n}), skipping insert")
        else:
            sys.exit(f"citizens has {n} rows, expected 0 or {COUNT}. Reset the volume.")

    write_csv(creds)


if __name__ == "__main__":
    main()
