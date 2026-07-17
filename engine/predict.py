"""Layer 2 -- Predict: category + display_name for every transaction, plus the
corrections store. Purchases get their category from the Layer-1 merchant
match. Transfers/income/cash have no merchant, so we apply the same
amount/time/recurrence context rules DATA_SPEC uses to construct the
ambiguous cases -- this is transparent rules, no training. The corrections
store is the only thing that "learns": once a user corrects a prediction, the
same (user, key) always resolves via that correction from then on.

Reads only INPUT columns (txn_id, user_id, raw_description, amount, currency,
timestamp, channel, counterparty_ref) -- CLAUDE.md rule 4.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from engine.clean import clean
from engine.normalize import normalize
from engine.schema import Counterparty, EnrichedTransaction, Merchant, slugify

CORRECTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "corrections.json"
RECURRING_THRESHOLD = 2  # a counterparty seen >= this many times for a user counts as "recurring"
SALARY_MIN_AMOUNT = 1000
REMITTANCE_MIN_AMOUNT = 800


# ---------------------------------------------------------------------------
# Recurring-counterparty context (built only from INPUT columns)
# ---------------------------------------------------------------------------
class RecipientStats:
    """How often each (user_id, counterparty_ref) pair recurs -- the only
    "history" Layer 2 gets, used to tell a recurring recipient from a one-off."""

    def __init__(self):
        self.counts = Counter()

    def observe(self, user_id, counterparty_ref):
        if counterparty_ref:
            self.counts[(user_id, counterparty_ref)] += 1

    def is_recurring(self, user_id, counterparty_ref):
        if not counterparty_ref:
            return False
        return self.counts[(user_id, counterparty_ref)] >= RECURRING_THRESHOLD

    @classmethod
    def from_raw_txns(cls, raw_txns):
        stats = cls()
        for t in raw_txns:
            stats.observe(t["user_id"], t.get("counterparty_ref", ""))
        return stats


# ---------------------------------------------------------------------------
# Corrections store -- data/corrections.json, keyed by user_id -> key -> correction
# ---------------------------------------------------------------------------
def load_corrections():
    if CORRECTIONS_PATH.exists():
        with open(CORRECTIONS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_correction(user_id, key, correction):
    corrections = load_corrections()
    corrections.setdefault(user_id, {})[key] = correction
    CORRECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CORRECTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)


def lookup_correction(user_id, key):
    return load_corrections().get(user_id, {}).get(key)


def correction_key_for(raw_description, channel, counterparty_ref):
    if channel in ("transfer", "wallet") and counterparty_ref:
        return counterparty_ref
    return normalize(raw_description)


def apply_correction(user_id, raw_description, channel, counterparty_ref, category, display_name, txn_type=None):
    key = correction_key_for(raw_description, channel, counterparty_ref)
    save_correction(user_id, key, {"category": category, "display_name": display_name, "type": txn_type})
    return key


# ---------------------------------------------------------------------------
# Purchase / cash / transfer context rules
# ---------------------------------------------------------------------------
def predict_purchase(clean_result):
    merchant = clean_result["merchant"]
    if merchant:
        return {"category": merchant["category"], "display_name": merchant["name_en"],
                "merchant_name": merchant["name_en"]}
    fallback_name = clean_result["normalized"].title() or "Unknown Purchase"
    return {"category": "shopping", "display_name": fallback_name, "merchant_name": None}


def predict_cash():
    return {"category": "cash", "display_name": "Cash Withdrawal"}


def predict_transfer_or_income(amount, timestamp, counterparty_ref, recipient_stats, user_id):
    recurring = recipient_stats.is_recurring(user_id, counterparty_ref)
    day = timestamp.day
    hour = timestamp.hour
    weekday = timestamp.weekday()  # Mon=0..Sun=6; Fri=4, Sat=5 is the KSA weekend
    abs_amount = abs(amount)
    is_round_multiple_50 = abs_amount >= 50 and abs_amount % 50 == 0
    is_round_amount = abs_amount in (100, 200, 500)
    is_odd_amount = abs_amount % 10 != 0

    # rule 5: inbound + recurring sender -> salary
    if amount > 0 and abs_amount >= SALARY_MIN_AMOUNT and recurring:
        return {"category": "income", "display_name": "Salary", "counterparty_kind": "business", "is_ambiguous": True}

    # rule 1: end-of-month + round amount + recurring recipient -> bill/rent
    if amount < 0 and day >= 26 and is_round_multiple_50 and recurring:
        return {"category": "bills", "display_name": "Rent / Bill", "counterparty_kind": "business", "is_ambiguous": True}

    # rule 6 (proxy for "international beneficiary"): large recurring outbound, not a bill -> remittance
    if amount < 0 and abs_amount >= REMITTANCE_MIN_AMOUNT and recurring and not is_round_multiple_50:
        return {"category": "transfer", "display_name": "Remittance", "counterparty_kind": "person", "is_ambiguous": True}

    # rule 3: odd amount to a recurring "friend" -> split (qattah)
    if is_odd_amount and recurring:
        return {"category": "transfer", "display_name": "Split", "counterparty_kind": "person", "is_ambiguous": True}

    # rule 2: weekday evening + amount 30-200 + one-off -> food via wallet
    if not recurring and weekday not in (4, 5) and 18 <= hour <= 23 and 30 <= abs_amount <= 200:
        return {"category": "food", "display_name": "Food", "counterparty_kind": "person", "is_ambiguous": True}

    # rule 4: round amount + one-off -> gift
    if not recurring and is_round_amount:
        return {"category": "transfer", "display_name": "Gift", "counterparty_kind": "person", "is_ambiguous": True}

    # small outbound, no other signal -> topping up own wallet
    if amount < 0 and abs_amount <= 100:
        return {"category": "transfer", "display_name": "Wallet Top-up", "counterparty_kind": "wallet", "is_ambiguous": True}

    return {"category": "transfer", "display_name": "Transfer", "counterparty_kind": "person", "is_ambiguous": True}


# ---------------------------------------------------------------------------
# enrich() -- wires Layer 1 (clean) + Layer 2 (predict) + corrections
# ---------------------------------------------------------------------------
def enrich(raw_txn: dict, recipient_stats: RecipientStats = None) -> EnrichedTransaction:
    txn_id = raw_txn["txn_id"]
    user_id = raw_txn["user_id"]
    raw_description = raw_txn["raw_description"]
    amount = float(raw_txn["amount"])
    currency = raw_txn.get("currency", "SAR")
    timestamp = raw_txn["timestamp"]
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)
    channel = raw_txn["channel"]
    counterparty_ref = raw_txn.get("counterparty_ref") or ""

    key = correction_key_for(raw_description, channel, counterparty_ref)
    correction = lookup_correction(user_id, key)
    if correction:
        txn_type = correction.get("type") or ("cash" if channel == "atm" else
                                               "transfer" if channel in ("transfer", "wallet") else "purchase")
        merchant = Merchant(name=correction["display_name"], slug=slugify(correction["display_name"])) \
            if txn_type == "purchase" else None
        return EnrichedTransaction(
            txn_id=txn_id, raw_description=raw_description, type=txn_type,
            display_name=correction["display_name"], category=correction["category"],
            merchant=merchant, counterparty=None, amount=amount, currency=currency,
            timestamp=timestamp, confidence=1.0, resolved_by="correction", is_ambiguous=False,
        )

    if channel == "atm":
        pred = predict_cash()
        return EnrichedTransaction(
            txn_id=txn_id, raw_description=raw_description, type="cash",
            display_name=pred["display_name"], category=pred["category"],
            merchant=None, counterparty=None, amount=amount, currency=currency,
            timestamp=timestamp, confidence=0.95, resolved_by="rules", is_ambiguous=False,
        )

    if channel in ("transfer", "wallet"):
        stats = recipient_stats or RecipientStats()
        pred = predict_transfer_or_income(amount, timestamp, counterparty_ref, stats, user_id)
        txn_type = "income" if pred["category"] == "income" else "transfer"
        counterparty = Counterparty(label=pred["display_name"], kind=pred["counterparty_kind"])
        return EnrichedTransaction(
            txn_id=txn_id, raw_description=raw_description, type=txn_type,
            display_name=pred["display_name"], category=pred["category"],
            merchant=None, counterparty=counterparty, amount=amount, currency=currency,
            timestamp=timestamp, confidence=0.75, resolved_by="rules", is_ambiguous=pred["is_ambiguous"],
        )

    # pos / ecom / sadad -- real purchase, resolved through Layer 1
    clean_result = clean(raw_description)
    pred = predict_purchase(clean_result)
    merchant_obj = Merchant(name=pred["merchant_name"], slug=slugify(pred["merchant_name"])) \
        if pred["merchant_name"] else None
    return EnrichedTransaction(
        txn_id=txn_id, raw_description=raw_description, type="purchase",
        display_name=pred["display_name"], category=pred["category"],
        merchant=merchant_obj, counterparty=None, amount=amount, currency=currency,
        timestamp=timestamp, confidence=clean_result["confidence"], resolved_by=clean_result["resolved_by"],
        is_ambiguous=False,
    )
