"""Shared per-user aggregation -- the one place that turns a user's enriched
transactions for a month into totals / category breakdown / top merchants.

Both the `/user/{user_id}/dashboard` API endpoint and Layer 3's chat()
build their view from build_dashboard() here, so the chat assistant always
reasons over exactly what the dashboard shows -- never a different slice of
the data.

Reads only INPUT columns from transactions.csv (via engine.predict.enrich,
CLAUDE.md rule 4) plus users.csv, which is persona ground-truth the engine is
allowed to read for display purposes (income/persona/city), not an answer key.
"""

import csv
from collections import defaultdict
from pathlib import Path

from engine.predict import RecipientStats, enrich

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USERS_PATH = DATA_DIR / "users.csv"
TXN_PATH = DATA_DIR / "transactions.csv"

CATEGORY_LABELS_AR = {
    "food": "طعام ومطاعم", "groceries": "بقالة وتموين", "transport": "نقل ووقود",
    "shopping": "تسوّق", "bills": "فواتير ومرافق", "telecom": "اتصالات وإنترنت",
    "health": "صحة وصيدليات", "entertainment": "ترفيه واشتراكات", "travel": "سفر وطيران",
    "education": "تعليم", "government": "خدمات حكومية ورسوم", "charity": "صدقات وتبرعات",
    "transfer": "تحويلات", "income": "دخل ورواتب", "cash": "سحب نقدي",
}

TOP_MERCHANTS_N = 8
RECENT_TRANSACTIONS_N = 15

_all_raw_txns = None
_recipient_stats = None
_users_by_id = None


def _load_raw_txns():
    with open(TXN_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [{
        "txn_id": r["txn_id"], "user_id": r["user_id"], "raw_description": r["raw_description"],
        "amount": float(r["amount"]), "currency": r["currency"], "timestamp": r["timestamp"],
        "channel": r["channel"], "counterparty_ref": r["counterparty_ref"],
    } for r in rows]


def _load_users():
    with open(USERS_PATH, encoding="utf-8-sig") as f:
        return {r["user_id"]: r for r in csv.DictReader(f)}


def _get_all_raw_txns():
    global _all_raw_txns, _recipient_stats
    if _all_raw_txns is None:
        _all_raw_txns = _load_raw_txns()
        _recipient_stats = RecipientStats.from_raw_txns(_all_raw_txns)
    return _all_raw_txns, _recipient_stats


def _get_users():
    global _users_by_id
    if _users_by_id is None:
        _users_by_id = _load_users()
    return _users_by_id


def latest_month_for_user(user_id: str) -> str:
    all_raw, _ = _get_all_raw_txns()
    months = sorted({t["timestamp"][:7] for t in all_raw if t["user_id"] == user_id})
    if not months:
        raise ValueError(f"no transactions for user {user_id}")
    return months[-1]


def build_dashboard(user_id: str, month: str = None) -> dict:
    """month: 'YYYY-MM', or None to use the user's latest available month.

    Returns {user, month, totals, by_category, top_merchants, transactions}
    where `transactions` is the list[EnrichedTransaction] for that month.
    """
    users = _get_users()
    user_row = users.get(user_id)
    if not user_row:
        raise ValueError(f"unknown user_id {user_id}")

    if month is None:
        month = latest_month_for_user(user_id)

    all_raw, stats = _get_all_raw_txns()
    user_raw = [t for t in all_raw if t["user_id"] == user_id and t["timestamp"].startswith(month)]
    enriched = [enrich(t, recipient_stats=stats) for t in user_raw]

    income = sum(e.amount for e in enriched if e.type == "income")
    spending = sum(-e.amount for e in enriched if e.amount < 0)
    net = income - spending
    savings_rate = (net / income) if income > 0 else 0.0

    spend_by_cat = defaultdict(lambda: {"count": 0, "total": 0.0})
    for e in enriched:
        if e.amount < 0:
            spend_by_cat[e.category]["count"] += 1
            spend_by_cat[e.category]["total"] += -e.amount
    by_category = [
        {
            "category": cat, "label_ar": CATEGORY_LABELS_AR.get(cat, cat),
            "count": v["count"], "total": round(v["total"], 2),
            "pct": round(100 * v["total"] / spending, 1) if spending else 0.0,
        }
        for cat, v in sorted(spend_by_cat.items(), key=lambda kv: -kv[1]["total"])
    ]

    merchant_agg = defaultdict(lambda: {"count": 0, "total": 0.0, "slug": ""})
    for e in enriched:
        if e.merchant and e.amount < 0:
            m = merchant_agg[e.merchant.name]
            m["count"] += 1
            m["total"] += -e.amount
            m["slug"] = e.merchant.slug
    top_merchants = [
        {"name": name, "slug": v["slug"], "total": round(v["total"], 2), "count": v["count"]}
        for name, v in sorted(merchant_agg.items(), key=lambda kv: -kv[1]["total"])[:TOP_MERCHANTS_N]
    ]

    return {
        "user": {
            "user_id": user_id,
            "persona": user_row["persona"],
            "income_monthly": float(user_row["income_monthly_sar"]),
            "home_city": user_row["home_city"],
        },
        "month": month,
        "totals": {
            "income": round(income, 2), "spending": round(spending, 2),
            "net": round(net, 2), "savings_rate": round(savings_rate, 4),
        },
        "by_category": by_category,
        "top_merchants": top_merchants,
        "transactions": enriched,
    }
