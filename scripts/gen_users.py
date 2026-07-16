"""Generate data/users.csv (Table 2 in docs/DATA_SPEC.md).

~150 synthetic users spread evenly across the 6 persona archetypes, each
following that persona's income/rent/subs/qattah/remittance rules from the
spec. `recurring_subs` references real merchant_id values pulled from
data/merchants.csv (must be run after scripts/gen_merchants.py).

This is persona ground-truth: it is hidden from the engine and used only to
drive realistic transaction generation + evaluation later.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

RNG_SEED = 7
USERS_PER_PERSONA = 25  # 6 personas x 25 = 150

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MERCHANTS_PATH = DATA_DIR / "merchants.csv"
OUT_PATH = DATA_DIR / "users.csv"

REFERENCE_DATE = date(2026, 6, 30)  # anchor "today" for the synthetic history

CITIES = ["RYD", "JED", "DMM", "MAK", "MAD", "KHOBAR", "TIF", "ABHA",
          "QASSIM", "TABUK", "HAIL", "JIZAN", "NJRAN", "YANBU"]
CITY_WEIGHTS = [6, 5, 4, 2, 2, 3, 1, 1, 1, 1, 1, 1, 1, 1]

# ---------------------------------------------------------------------------
# Persona archetypes -- ranges/probabilities from docs/DATA_SPEC.md
# ---------------------------------------------------------------------------
PERSONAS = {
    "student": dict(
        age_range=(18, 24), income_source="family_support", income_range=(1500, 2500),
        rent_prob=0.05, rent_range=(800, 1800),
        qattah_prob=0.85, remittance_prob=0.03,
        sub_categories=["entertainment", "telecom"], sub_count_range=(1, 2),
    ),
    "young_family": dict(
        age_range=(25, 34), income_source="salary", income_range=(12000, 18000),
        rent_prob=0.90, rent_range=(2500, 6000),
        qattah_prob=0.20, remittance_prob=0.05,
        sub_categories=["bills", "telecom", "education"], sub_count_range=(2, 4),
    ),
    "gig_worker": dict(
        age_range=(22, 30), income_source="gig_platform", income_range=(4000, 9000),
        rent_prob=0.40, rent_range=(1200, 3000),
        qattah_prob=0.30, remittance_prob=0.10,
        sub_categories=["telecom"], sub_count_range=(0, 1),
    ),
    "professional": dict(
        age_range=(30, 45), income_source="salary", income_range=(20000, 40000),
        rent_prob=0.60, rent_range=(3500, 9000),
        qattah_prob=0.40, remittance_prob=0.25,
        sub_categories=["entertainment", "telecom", "travel"], sub_count_range=(2, 4),
    ),
    "retiree": dict(
        age_range=(55, 75), income_source="pension", income_range=(4000, 8000),
        rent_prob=0.15, rent_range=(1500, 3500),
        qattah_prob=0.10, remittance_prob=0.05,
        sub_categories=["bills", "telecom"], sub_count_range=(1, 2),
    ),
    "business_owner": dict(
        age_range=(30, 55), income_source="business_revenue", income_range=(15000, 80000),
        rent_prob=0.50, rent_range=(4000, 12000),
        qattah_prob=0.15, remittance_prob=0.10,
        sub_categories=["telecom", "entertainment"], sub_count_range=(1, 3),
    ),
}


def age_band(age):
    if age <= 24:
        return "18-24"
    if age <= 34:
        return "25-34"
    if age <= 44:
        return "35-44"
    if age <= 54:
        return "45-54"
    return "55+"


def load_recurring_sub_pool():
    """merchant_id pool per category, restricted to known monthly-recurring merchants."""
    pool = {}
    with open(MERCHANTS_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["recurrence"] != "monthly" or row["in_directory"] != "True":
                continue
            pool.setdefault(row["category"], []).append(row["merchant_id"])
    return pool


def pick_recurring_subs(rng, sub_pool, categories, count_range):
    candidates = []
    for cat in categories:
        candidates.extend(sub_pool.get(cat, []))
    candidates = sorted(set(candidates))
    if not candidates:
        return []
    n = rng.randint(*count_range)
    n = min(n, len(candidates))
    return sorted(rng.sample(candidates, k=n)) if n > 0 else []


def build_user(rng, sub_pool, persona, cfg, index):
    age = rng.randint(*cfg["age_range"])
    income = round(rng.uniform(*cfg["income_range"]), 2)
    payday_day = rng.randint(1, 28)
    home_city = rng.choices(CITIES, weights=CITY_WEIGHTS, k=1)[0]

    has_rent = rng.random() < cfg["rent_prob"]
    rent_amount = round(rng.uniform(*cfg["rent_range"]), 2) if has_rent else 0.0
    rent_day = rng.randint(1, 28) if has_rent else ""

    recurring_subs = pick_recurring_subs(rng, sub_pool, cfg["sub_categories"], cfg["sub_count_range"])

    does_qattah = rng.random() < cfg["qattah_prob"]
    does_remittance = rng.random() < cfg["remittance_prob"]

    months = rng.randint(6, 12)
    history_end = REFERENCE_DATE
    history_start = history_end - timedelta(days=months * 30)

    return {
        "user_id": f"U{index:04d}",
        "persona": persona,
        "age_band": age_band(age),
        "income_source": cfg["income_source"],
        "income_monthly_sar": income,
        "payday_day": payday_day,
        "home_city": home_city,
        "has_rent": has_rent,
        "rent_amount": rent_amount,
        "rent_day": rent_day,
        "recurring_subs": "|".join(recurring_subs),
        "does_qattah": does_qattah,
        "does_remittance": does_remittance,
        "history_start": history_start.isoformat(),
        "history_end": history_end.isoformat(),
    }


def main():
    if not MERCHANTS_PATH.exists():
        raise SystemExit("data/merchants.csv not found -- run scripts/gen_merchants.py first")

    rng = random.Random(RNG_SEED)
    sub_pool = load_recurring_sub_pool()

    rows = []
    index = 1
    for persona, cfg in PERSONAS.items():
        for _ in range(USERS_PER_PERSONA):
            rows.append(build_user(rng, sub_pool, persona, cfg, index))
            index += 1
    rng.shuffle(rows)
    # re-number sequentially after shuffling so user_id order doesn't reveal persona
    for i, row in enumerate(rows, start=1):
        row["user_id"] = f"U{i:04d}"

    fieldnames = [
        "user_id", "persona", "age_band", "income_source", "income_monthly_sar",
        "payday_day", "home_city", "has_rent", "rent_amount", "rent_day",
        "recurring_subs", "does_qattah", "does_remittance",
        "history_start", "history_end",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Rule 7: test before moving on -- print a quick self-check.
    print(f"Wrote {len(rows)} users to {OUT_PATH}")
    for persona in PERSONAS:
        count = sum(1 for r in rows if r["persona"] == persona)
        print(f"  {persona:16s} {count}")
    no_subs = sum(1 for r in rows if not r["recurring_subs"])
    print(f"Users with 0 recurring_subs: {no_subs}")


if __name__ == "__main__":
    main()
