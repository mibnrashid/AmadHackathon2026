"""Generate data/transactions.csv (~30,000 rows) and data/golden_set.csv (~200 rows).

Truth-first: for every row we decide the true merchant/category/intent FIRST,
then corrupt it into raw_description (CLAUDE.md rule 3). The answer-key
columns exist only for eval/golden_set -- engine/*.py must never read them
(CLAUDE.md rule 4).

Must run after gen_merchants.py and gen_users.py.
"""

import csv
import json
import random
import re
import string
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_merchants  # for the real-anchor SEED_MERCHANTS ordering (power-law weight)

RNG_SEED = 11

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MERCHANTS_PATH = DATA_DIR / "merchants.csv"
USERS_PATH = DATA_DIR / "users.csv"
TXN_PATH = DATA_DIR / "transactions.csv"
GOLDEN_PATH = DATA_DIR / "golden_set.csv"

CATEGORIES = [
    "food", "groceries", "transport", "shopping", "bills", "telecom",
    "health", "entertainment", "travel", "education", "government", "charity",
    "transfer", "income", "cash",
]

ARABIC_RE = re.compile(r"[؀-ۿ]")
TASHKEEL = "ًٌٍَُِّْ"
TATWEEL = "ـ"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

PREFIXES = ["POS ", "SP *", "MADA ", "APPLEPAY *"]
CITY_SUFFIX_CODES = ["RYD", "JED", "DMM", "SA"]
GARBAGE_TEMPLATES = ["POS 000000", "UNKNOWN MERCHANT", "TXN REF 00000000",
                     "*** ***", "PURCHASE", "REF#00000000", "N/A"]
STC_BARE = "STC PAY TRANSFER"
TRANSFER_TEMPLATES = ["STC PAY TRANSFER", "MADA TRANSFER", "BANK TRANSFER",
                      "WALLET TRANSFER", "URPAY TRANSFER"]
EMPLOYER_TOKENS = ["AL RAJHI CORP", "SABIC", "STC GROUP", "ARAMCO SVC",
                   "ELM CO", "SOLUTIONS LLC", "GULF HOLDING"]

# ---------------------------------------------------------------------------
# Persona spend bias -- which categories each persona over/under-indexes on
# ---------------------------------------------------------------------------
PERSONA_CATEGORY_BIAS = {
    "student": {"food": 3, "telecom": 2, "entertainment": 2.5, "transport": 1,
                "shopping": 1, "groceries": 0.5, "health": 0.5, "government": 0.3,
                "charity": 0.3, "travel": 0.2, "education": 0.5, "bills": 0.2},
    "young_family": {"groceries": 3, "health": 2, "education": 2, "bills": 2,
                     "food": 1, "shopping": 1.5, "telecom": 1, "transport": 1,
                     "entertainment": 0.7, "government": 0.5, "charity": 0.7, "travel": 0.5},
    "gig_worker": {"transport": 3, "food": 2.5, "groceries": 1, "telecom": 1,
                   "bills": 0.5, "shopping": 0.8, "health": 0.5, "entertainment": 0.7,
                   "government": 0.3, "charity": 0.2, "travel": 0.2, "education": 0.2},
    "professional": {"food": 2, "travel": 2.5, "shopping": 2.5, "entertainment": 2,
                     "transport": 1.2, "groceries": 1, "health": 1, "telecom": 1,
                     "bills": 1, "government": 0.5, "charity": 0.7, "education": 0.7},
    "retiree": {"health": 3, "bills": 2, "charity": 2, "groceries": 1.5, "food": 0.7,
                "government": 1, "transport": 0.7, "shopping": 0.5, "telecom": 0.7,
                "entertainment": 0.3, "travel": 0.3, "education": 0.1},
    "business_owner": {"shopping": 1.5, "travel": 1.5, "food": 1.5, "transport": 1.2,
                       "bills": 1.2, "groceries": 1, "telecom": 1, "health": 1,
                       "entertainment": 1, "government": 0.7, "charity": 0.7, "education": 0.5},
}

CHANNEL_WEIGHTS = {
    "food": {"pos": 0.5, "ecom": 0.5}, "groceries": {"pos": 0.85, "ecom": 0.15},
    "transport": {"pos": 0.9, "ecom": 0.1}, "shopping": {"pos": 0.4, "ecom": 0.6},
    "bills": {"sadad": 0.8, "pos": 0.2}, "telecom": {"sadad": 0.6, "ecom": 0.4},
    "health": {"pos": 0.8, "ecom": 0.2}, "entertainment": {"ecom": 1.0},
    "travel": {"ecom": 0.8, "pos": 0.2}, "education": {"ecom": 0.7, "sadad": 0.3},
    "government": {"sadad": 0.9, "pos": 0.1}, "charity": {"sadad": 0.5, "ecom": 0.5},
}


def is_arabic_text(s):
    return bool(ARABIC_RE.search(s))


def to_arabic_digits(s):
    return "".join(ARABIC_DIGITS[int(ch)] if ch.isdigit() else ch for ch in s)


def add_months(d, n):
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def months_in_window(start, end):
    out = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def random_dt(rng, start, end, hour_range=None):
    days = (end - start).days
    if days <= 0:
        days = 1
    d = start + timedelta(days=rng.randint(0, days))
    if hour_range:
        hour = rng.randint(*hour_range)
    else:
        hour = rng.randint(7, 22)
    return datetime(d.year, d.month, d.day, hour, rng.randint(0, 59), rng.randint(0, 59))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_merchants():
    with open(MERCHANTS_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    merchants = []
    for r in rows:
        merchants.append({
            "merchant_id": r["merchant_id"], "name_en": r["name_en"], "name_ar": r["name_ar"],
            "category": r["category"], "in_directory": r["in_directory"] == "True",
            "descriptor_patterns": json.loads(r["descriptor_patterns"]),
            "amount_mean": float(r["amount_mean"]), "amount_std": float(r["amount_std"]),
            "recurrence": r["recurrence"], "aggregator": r["aggregator"],
            "cities": json.loads(r["cities"]),
        })
    return merchants


def load_users():
    with open(USERS_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    users = []
    for r in rows:
        users.append({
            "user_id": r["user_id"], "persona": r["persona"], "age_band": r["age_band"],
            "income_source": r["income_source"], "income_monthly_sar": float(r["income_monthly_sar"]),
            "payday_day": int(r["payday_day"]), "home_city": r["home_city"],
            "has_rent": r["has_rent"] == "True", "rent_amount": float(r["rent_amount"]),
            "rent_day": r["rent_day"], "recurring_subs": r["recurring_subs"].split("|") if r["recurring_subs"] else [],
            "does_qattah": r["does_qattah"] == "True", "does_remittance": r["does_remittance"] == "True",
            "history_start": date.fromisoformat(r["history_start"]),
            "history_end": date.fromisoformat(r["history_end"]),
        })
    return users


# ---------------------------------------------------------------------------
# Corruption pipeline (purchase raw_description)
# ---------------------------------------------------------------------------
def op_abbreviate(token, rng):
    words = token.split()
    if len(words) > 1:
        return "".join(w[0] for w in words if w[0].isalnum())
    stripped = re.sub(r"[AEIOU]", "", token)
    return stripped[:4] if len(stripped) >= 2 else token[:3]


def op_space_symbol(token, rng):
    return token.replace(" ", rng.choice(["_", "-"]))


def gen_id_suffix(rng, arabic_digits=False):
    kind = rng.choice(["underscore", "hash", "space"])
    num = str(rng.randint(1000, 99999))
    if arabic_digits:
        num = to_arabic_digits(num)
    if kind == "underscore":
        return f"_{num}"
    if kind == "hash":
        return f"#{num}"
    return f" {num}"


def arabic_noise(name_ar, rng):
    s = name_ar
    if rng.random() < 0.3 and "ا" in s:
        s = s.replace("ا", rng.choice(["أ", "إ", "آ", "ا"]), 1)
    if rng.random() < 0.2 and len(s) > 2:
        pos = rng.randint(1, len(s) - 1)
        s = s[:pos] + TATWEEL + s[pos:]
    if rng.random() < 0.15 and len(s) > 1:
        pos = rng.randint(0, len(s) - 1)
        s = s[:pos + 1] + rng.choice(TASHKEEL) + s[pos + 1:]
    return s


def corrupt_merchant_name(merchant, rng):
    ops_fired = []
    use_arabic = rng.random() < 0.25
    patterns = merchant["descriptor_patterns"]
    use_known_pattern = rng.random() < 0.6 and patterns

    if use_arabic:
        arabic_patterns = [p for p in patterns if is_arabic_text(p)]
        if use_known_pattern and arabic_patterns:
            token = rng.choice(arabic_patterns)
            ops_fired.append("known_pattern")
        else:
            token = merchant["name_ar"]
            ops_fired.append("arabic_base")
        noisy = arabic_noise(token, rng)
        if noisy != token:
            ops_fired.append("arabic_noise")
        token = noisy
    else:
        if use_known_pattern:
            token = rng.choice(patterns)
            ops_fired.append("known_pattern")
        else:
            token = merchant["name_en"].upper().replace("'", "")
            if rng.random() < 0.35:
                token = op_abbreviate(token, rng)
                ops_fired.append("abbreviate")
            else:
                ops_fired.append("uppercase")
            if rng.random() < 0.25:
                token = op_space_symbol(token, rng)
                ops_fired.append("space_symbol")

    if merchant["aggregator"] and rng.random() < 0.7:
        token = f"{merchant['aggregator']}*{token}"
        ops_fired.append("aggregator_wrap")

    if rng.random() < 0.35:
        token = f"{rng.choice(PREFIXES)}{token}"
        ops_fired.append("prefix_inject")
    if rng.random() < 0.30:
        token = f"{token}{gen_id_suffix(rng, arabic_digits=use_arabic and rng.random() < 0.5)}"
        ops_fired.append("id_inject")
    if rng.random() < 0.25:
        token = f"{token} {rng.choice(CITY_SUFFIX_CODES)}"
        ops_fired.append("city_code")
    if rng.random() < 0.10:
        width = rng.choice([10, 12, 14])
        token = token[:width]
        ops_fired.append("truncate")

    return token, ops_fired


def gen_garbage_raw(rng):
    if rng.random() < 0.5:
        return rng.choice(GARBAGE_TEMPLATES), ["garbage"]
    length = rng.randint(6, 14)
    chars = string.ascii_uppercase + string.digits
    return "".join(rng.choice(chars) for _ in range(length)), ["garbage"]


def gen_transfer_raw(rng):
    if rng.random() < 0.45:
        return STC_BARE, ["known_template"]
    base = rng.choice(TRANSFER_TEMPLATES)
    ops = ["known_template"]
    if rng.random() < 0.5:
        ref = rng.randint(100000, 999999)
        base = f"{base} REF{ref}"
        ops.append("id_inject")
    return base, ops


# ---------------------------------------------------------------------------
# Merchant selection (power-law known + uniform unknown)
# ---------------------------------------------------------------------------
def build_merchant_pools(merchants):
    top20 = {m[0] for m in gen_merchants.SEED_MERCHANTS[:20]}
    top_rest = {m[0] for m in gen_merchants.SEED_MERCHANTS[20:]}
    known = [m for m in merchants if m["in_directory"]]
    unknown = [m for m in merchants if not m["in_directory"]]

    persona_weighted = {}
    for persona, bias in PERSONA_CATEGORY_BIAS.items():
        weights = []
        for m in known:
            base_w = 40.0 if m["name_en"] in top20 else (10.0 if m["name_en"] in top_rest else 1.0)
            weights.append(base_w * bias.get(m["category"], 1.0))
        persona_weighted[persona] = (known, weights)

    fx_pool = [m for m in known if m["category"] in ("entertainment", "travel")]
    return persona_weighted, unknown, fx_pool


def pick_channel(rng, category):
    weights = CHANNEL_WEIGHTS.get(category, {"pos": 1.0})
    channels, probs = zip(*weights.items())
    return rng.choices(channels, weights=probs, k=1)[0]


def make_purchase_row(rng, user, merchant, ts, currency="SAR"):
    raw, ops = corrupt_merchant_name(merchant, rng)
    mean, std = merchant["amount_mean"], merchant["amount_std"]
    amount = -abs(round(rng.gauss(mean, std if std > 0 else mean * 0.3), 2))
    if amount == 0:
        amount = -round(mean, 2)
    channel = pick_channel(rng, merchant["category"])
    return {
        "user_id": user["user_id"], "raw_description": raw, "amount": amount,
        "currency": currency, "timestamp": ts, "channel": channel, "counterparty_ref": "",
        "txn_type": "purchase", "true_merchant_id": merchant["merchant_id"],
        "true_merchant_name": merchant["name_en"], "true_category": merchant["category"],
        "true_intent": "", "is_ambiguous": False, "is_in_directory": merchant["in_directory"],
        "is_recurring_instance": False, "corruption_ops": ops,
        "expected_counterparty_id": "", "mark_for_correction": False, "is_golden": False,
    }


def generate_recurring_sub_rows(rng, user, merchants_by_id, window_months):
    rows = []
    for mid in user["recurring_subs"]:
        merchant = merchants_by_id.get(mid)
        if not merchant:
            continue
        for month_start in window_months:
            day = rng.randint(1, 27)
            try:
                d = date(month_start.year, month_start.month, day)
            except ValueError:
                continue
            ts = datetime(d.year, d.month, d.day, rng.randint(6, 21), rng.randint(0, 59))
            row = make_purchase_row(rng, user, merchant, ts)
            row["is_recurring_instance"] = True
            rows.append(row)
    return rows


def generate_purchase_rows(rng, user, persona_pools, unknown_pool, fx_pool, count, unknown_frac, fx_frac):
    rows = []
    known_pool, known_weights = persona_pools[user["persona"]]
    n_unknown = round(count * unknown_frac)
    n_fx = round(count * fx_frac) if fx_pool else 0
    n_known = max(0, count - n_unknown - n_fx)

    for _ in range(n_known):
        merchant = rng.choices(known_pool, weights=known_weights, k=1)[0]
        ts = random_dt(rng, user["history_start"], user["history_end"])
        rows.append(make_purchase_row(rng, user, merchant, ts))
    for _ in range(n_unknown):
        if not unknown_pool:
            break
        merchant = rng.choice(unknown_pool)
        ts = random_dt(rng, user["history_start"], user["history_end"])
        rows.append(make_purchase_row(rng, user, merchant, ts))
    for _ in range(n_fx):
        merchant = rng.choice(fx_pool)
        ts = random_dt(rng, user["history_start"], user["history_end"])
        row = make_purchase_row(rng, user, merchant, ts, currency="USD")
        row["amount"] = -abs(round(rng.uniform(5, 15) if merchant["category"] == "entertainment"
                                    else rng.uniform(50, 500), 2))
        rows.append(row)
    return rows


def generate_garbage_rows(rng, user, count):
    rows = []
    for _ in range(count):
        raw, ops = gen_garbage_raw(rng)
        ts = random_dt(rng, user["history_start"], user["history_end"])
        amount = -abs(round(rng.uniform(10, 300), 2))
        rows.append({
            "user_id": user["user_id"], "raw_description": raw, "amount": amount,
            "currency": "SAR", "timestamp": ts, "channel": rng.choice(["pos", "ecom"]),
            "counterparty_ref": "", "txn_type": "purchase", "true_merchant_id": "",
            "true_merchant_name": "", "true_category": "", "true_intent": "",
            "is_ambiguous": False, "is_in_directory": False, "is_recurring_instance": False,
            "corruption_ops": ops, "expected_counterparty_id": "",
            "mark_for_correction": False, "is_golden": False,
        })
    return rows


def generate_cash_rows(rng, user, count):
    rows = []
    for _ in range(count):
        raw, ops = gen_transfer_raw(rng) if False else ("ATM WITHDRAWAL", [])
        if rng.random() < 0.3:
            raw = f"{raw} {rng.choice(CITY_SUFFIX_CODES)}"
            ops = ["city_code"]
        ts = random_dt(rng, user["history_start"], user["history_end"], hour_range=(6, 23))
        amount = -abs(round(rng.choice([100, 200, 300, 400, 500, 600, 1000]) + rng.uniform(-20, 20), 2))
        rows.append({
            "user_id": user["user_id"], "raw_description": raw, "amount": amount,
            "currency": "SAR", "timestamp": ts, "channel": "atm", "counterparty_ref": "",
            "txn_type": "cash", "true_merchant_id": "", "true_merchant_name": "",
            "true_category": "cash", "true_intent": "", "is_ambiguous": False,
            "is_in_directory": False, "is_recurring_instance": False, "corruption_ops": ops,
            "expected_counterparty_id": "", "mark_for_correction": False, "is_golden": False,
        })
    return rows


def generate_income_rows(rng, user, window_months):
    rows = []
    persona = user["persona"]
    irregular = persona in ("gig_worker", "business_owner")
    counterparty_kind = {
        "student": "family", "young_family": "employer", "gig_worker": "gig_platform",
        "professional": "employer", "retiree": "pension_fund", "business_owner": "self",
    }[persona]
    cp_ref = f"CP-{user['user_id']}-{counterparty_kind.upper()}"

    for month_start in window_months:
        events = rng.randint(1, 3) if irregular else 1
        for _ in range(events):
            day = rng.randint(1, 28) if irregular else min(user["payday_day"], 28)
            try:
                d = date(month_start.year, month_start.month, day)
            except ValueError:
                continue
            variance = 0.35 if irregular else 0.08
            amount = round(abs(rng.gauss(user["income_monthly_sar"] / events, user["income_monthly_sar"] * variance)), 2)
            employer = rng.choice(EMPLOYER_TOKENS)
            if counterparty_kind == "self":
                raw = "BUSINESS REVENUE TRANSFER"
            elif counterparty_kind == "gig_platform":
                raw = "GIG PLATFORM PAYOUT"
            elif counterparty_kind == "family":
                raw = "FAMILY SUPPORT TRANSFER"
            elif counterparty_kind == "pension_fund":
                raw = "PENSION TRANSFER"
            else:
                raw = f"SALARY TRANSFER - {employer}"
            ts = datetime(d.year, d.month, d.day, rng.randint(7, 12), rng.randint(0, 59))
            rows.append({
                "user_id": user["user_id"], "raw_description": raw, "amount": amount,
                "currency": "SAR", "timestamp": ts, "channel": "transfer", "counterparty_ref": cp_ref,
                "txn_type": "income", "true_merchant_id": "", "true_merchant_name": "",
                "true_category": "income", "true_intent": "", "is_ambiguous": False,
                "is_in_directory": False, "is_recurring_instance": not irregular,
                "corruption_ops": ["known_template"], "expected_counterparty_id": counterparty_kind,
                "mark_for_correction": False, "is_golden": False,
            })
    return rows


def transfer_row(rng, user, ts, amount, true_intent, true_category, cp_ref, expected_cp, is_recurring=False):
    raw, ops = gen_transfer_raw(rng)
    channel = "wallet" if raw == STC_BARE else rng.choice(["transfer", "wallet"])
    return {
        "user_id": user["user_id"], "raw_description": raw, "amount": amount,
        "currency": "SAR", "timestamp": ts, "channel": channel, "counterparty_ref": cp_ref,
        "txn_type": "transfer", "true_merchant_id": "", "true_merchant_name": "",
        "true_category": true_category, "true_intent": true_intent, "is_ambiguous": True,
        "is_in_directory": False, "is_recurring_instance": is_recurring, "corruption_ops": ops,
        "expected_counterparty_id": expected_cp, "mark_for_correction": False, "is_golden": False,
    }


def generate_transfer_rows(rng, user, window_months):
    rows = []
    uid = user["user_id"]

    # rule 1: end-of-month + round hundreds + recurring recipient -> bill/rent
    if user["has_rent"]:
        cp_ref = f"CP-{uid}-LANDLORD"
        for month_start in window_months:
            day = rng.randint(26, 28)
            try:
                d = date(month_start.year, month_start.month, day)
            except ValueError:
                d = date(month_start.year, month_start.month, 26)
            ts = datetime(d.year, d.month, d.day, rng.randint(9, 20), rng.randint(0, 59))
            amount = -abs(round(round(user["rent_amount"] / 50) * 50, 2))
            rows.append(transfer_row(rng, user, ts, amount, "bill", "bills", cp_ref, "landlord", is_recurring=True))

    # rule 2: weekday evening + amount 30-200 + one-off -> personal (food via wallet)
    n_food_wallet = rng.randint(2, 8)
    for _ in range(n_food_wallet):
        ts = random_dt(rng, user["history_start"], user["history_end"], hour_range=(18, 23))
        while ts.weekday() in (4, 5):
            ts = random_dt(rng, user["history_start"], user["history_end"], hour_range=(18, 23))
        amount = -round(rng.uniform(30, 200), 2)
        cp_ref = f"CP-{uid}-ONE-{rng.randint(100000,999999):x}"
        rows.append(transfer_row(rng, user, ts, amount, "personal", "food", cp_ref, "unknown"))

    # rule 3: odd amount to a recurring "friend" recipient -> split (qattah)
    if user["does_qattah"]:
        n_friends = rng.randint(1, 2)
        friend_refs = [f"CP-{uid}-FRIEND{i+1}" for i in range(n_friends)]
        for _ in range(rng.randint(4, 12)):
            ts = random_dt(rng, user["history_start"], user["history_end"])
            odd = rng.randint(15, 180)
            if odd % 10 == 0:
                odd += rng.randint(1, 9)
            amount = -float(odd) * (1 if rng.random() < 0.7 else -1)
            cp_ref = rng.choice(friend_refs)
            fidx = friend_refs.index(cp_ref) + 1
            rows.append(transfer_row(rng, user, ts, amount, "split", "transfer", cp_ref, f"friend:{fidx}"))

    # rule 4: round amount (100/200/500) + occasional + one-off -> gift
    for _ in range(rng.randint(1, 4)):
        ts = random_dt(rng, user["history_start"], user["history_end"])
        amount = float(rng.choice([100, 200, 500]))
        if rng.random() < 0.7:
            amount = -amount
        cp_ref = f"CP-{uid}-ONE-{rng.randint(100000,999999):x}"
        rows.append(transfer_row(rng, user, ts, amount, "gift", "transfer", cp_ref, "unknown"))

    # rule 5: inbound + large + monthly + employer sender -> salary (via disguised transfer)
    if user["persona"] in ("professional", "business_owner") and rng.random() < 0.4:
        cp_ref = f"CP-{uid}-EMPLOYER2"
        for month_start in rng.sample(window_months, k=min(len(window_months), rng.randint(2, 4))):
            day = rng.randint(25, 28)
            try:
                d = date(month_start.year, month_start.month, day)
            except ValueError:
                d = date(month_start.year, month_start.month, 25)
            ts = datetime(d.year, d.month, d.day, rng.randint(8, 12), rng.randint(0, 59))
            amount = round(rng.uniform(5000, 20000), 2)
            rows.append(transfer_row(rng, user, ts, amount, "salary", "income", cp_ref, "employer", is_recurring=True))

    # rule 6: outbound + international beneficiary -> remittance
    if user["does_remittance"]:
        n_beneficiaries = rng.randint(1, 2)
        beneficiary_refs = [f"CP-{uid}-BENEFICIARY{i+1}" for i in range(n_beneficiaries)]
        for _ in range(rng.randint(2, 6)):
            ts = random_dt(rng, user["history_start"], user["history_end"])
            amount = -round(rng.uniform(1000, 5000), 2)
            cp_ref = rng.choice(beneficiary_refs)
            bidx = beneficiary_refs.index(cp_ref) + 1
            rows.append(transfer_row(rng, user, ts, amount, "remittance", "transfer", cp_ref, f"beneficiary:{bidx}"))

    # topup: loading own wallet balance
    for _ in range(rng.randint(0, 3)):
        ts = random_dt(rng, user["history_start"], user["history_end"])
        amount = -float(rng.choice([20, 50, 100]))
        cp_ref = f"CP-{uid}-WALLET"
        rows.append(transfer_row(rng, user, ts, amount, "topup", "transfer", cp_ref, "wallet_provider"))

    # supplier transfers -- business_owner only
    if user["persona"] == "business_owner":
        n_suppliers = rng.randint(2, 3)
        supplier_refs = [f"CP-{uid}-SUPPLIER{i+1}" for i in range(n_suppliers)]
        for _ in range(rng.randint(3, 8)):
            ts = random_dt(rng, user["history_start"], user["history_end"], hour_range=(9, 18))
            amount = -round(rng.uniform(500, 5000), 2)
            cp_ref = rng.choice(supplier_refs)
            sidx = supplier_refs.index(cp_ref) + 1
            rows.append(transfer_row(rng, user, ts, amount, "personal", "transfer", cp_ref, f"supplier:{sidx}"))

    return rows


# ---------------------------------------------------------------------------
# Main assembly
# ---------------------------------------------------------------------------
def main():
    for path, script in [(MERCHANTS_PATH, "gen_merchants.py"), (USERS_PATH, "gen_users.py")]:
        if not path.exists():
            raise SystemExit(f"{path} not found -- run scripts/{script} first")

    rng = random.Random(RNG_SEED)
    merchants = load_merchants()
    merchants_by_id = {m["merchant_id"]: m for m in merchants}
    users = load_users()
    persona_pools, unknown_pool, fx_pool = build_merchant_pools(merchants)

    all_rows = []
    for user in users:
        window_months = months_in_window(user["history_start"], user["history_end"])
        n_months = max(len(window_months), 1)
        target = rng.randint(130, 270)

        sub_rows = generate_recurring_sub_rows(rng, user, merchants_by_id, window_months)
        transfer_rows = generate_transfer_rows(rng, user, window_months)
        income_rows = generate_income_rows(rng, user, window_months)
        cash_rows = generate_cash_rows(rng, user, max(1, round(0.03 * target)))

        used = len(sub_rows) + len(transfer_rows) + len(income_rows) + len(cash_rows)
        remaining = max(0, target - used)
        garbage_count = round(0.025 * target)
        remaining -= garbage_count
        garbage_rows = generate_garbage_rows(rng, user, max(0, garbage_count))

        remaining = max(0, remaining)
        purchase_rows = generate_purchase_rows(
            rng, user, persona_pools, unknown_pool, fx_pool, remaining,
            unknown_frac=0.12, fx_frac=0.02,
        )

        all_rows.extend(sub_rows + transfer_rows + income_rows + cash_rows + garbage_rows + purchase_rows)

    rng.shuffle(all_rows)

    # assign txn_id after shuffling
    for i, row in enumerate(all_rows, start=1):
        row["txn_id"] = f"T{i:06d}"

    # mark_for_correction: ~40 ambiguous rows held out with a known correct answer
    ambiguous_idx = [i for i, r in enumerate(all_rows) if r["is_ambiguous"]]
    rng.shuffle(ambiguous_idx)
    for i in ambiguous_idx[:40]:
        all_rows[i]["mark_for_correction"] = True

    # golden set: stratified ~200 rows
    golden_idx = set()

    def take(pred, n):
        pool = [i for i in range(len(all_rows)) if i not in golden_idx and pred(all_rows[i])]
        rng.shuffle(pool)
        for i in pool[:n]:
            golden_idx.add(i)

    take(lambda r: r["txn_type"] == "purchase" and r["is_in_directory"], 35)
    take(lambda r: r["txn_type"] == "purchase" and not r["is_in_directory"] and r["true_category"], 30)
    take(lambda r: not r["true_category"] and r["txn_type"] == "purchase", 15)  # garbage
    for intent in ("gift", "split", "personal", "remittance", "bill", "salary", "topup"):
        take(lambda r, intent=intent: r["true_intent"] == intent, 12)
    take(lambda r: is_arabic_text(r["raw_description"]), 20)
    take(lambda r: r["currency"] == "USD", 10)
    take(lambda r: r["txn_type"] == "cash", 10)
    take(lambda r: r["txn_type"] == "income", 10)

    for i in golden_idx:
        all_rows[i]["is_golden"] = True

    fieldnames = [
        "txn_id", "user_id", "raw_description", "amount", "currency", "timestamp",
        "channel", "counterparty_ref",
        "txn_type", "true_merchant_id", "true_merchant_name", "true_category",
        "true_intent", "is_ambiguous", "is_in_directory", "is_recurring_instance",
        "corruption_ops", "expected_counterparty_id", "mark_for_correction", "is_golden",
    ]

    def write_csv(path, rows):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                out = dict(row)
                out["timestamp"] = row["timestamp"].isoformat() if isinstance(row["timestamp"], datetime) else row["timestamp"]
                out["corruption_ops"] = json.dumps(row["corruption_ops"], ensure_ascii=False)
                writer.writerow(out)

    write_csv(TXN_PATH, all_rows)
    golden_rows = [all_rows[i] for i in sorted(golden_idx)]
    write_csv(GOLDEN_PATH, golden_rows)

    # Rule 7: test before moving on.
    total = len(all_rows)
    print(f"Wrote {total} transactions to {TXN_PATH}")
    print(f"Wrote {len(golden_rows)} golden rows to {GOLDEN_PATH}")
    from collections import Counter
    print("txn_type counts:", dict(Counter(r["txn_type"] for r in all_rows)))
    purchase_rows_all = [r for r in all_rows if r["txn_type"] == "purchase" and r["true_category"]]
    in_dir_true = sum(1 for r in purchase_rows_all if r["is_in_directory"])
    print(f"in_directory=true among identifiable purchases: {in_dir_true}/{len(purchase_rows_all)} "
          f"= {in_dir_true/len(purchase_rows_all):.1%}")
    garbage_n = sum(1 for r in all_rows if r["txn_type"] == "purchase" and not r["true_category"])
    print(f"garbage rows: {garbage_n} ({garbage_n/total:.1%})")
    print("mark_for_correction:", sum(1 for r in all_rows if r["mark_for_correction"]))
    print("is_golden:", sum(1 for r in all_rows if r["is_golden"]))
    print("true_intent counts:", dict(Counter(r["true_intent"] for r in all_rows if r["true_intent"])))


if __name__ == "__main__":
    main()
