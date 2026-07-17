"""Layer 3 -- Explain: turn clean EnrichedTransaction aggregates into a short
Arabic report or chat answer. The LLM only phrases text over already-clean,
already-categorized structured data -- it never sees raw strings and never
categorizes anything, so token cost stays tiny and there's nothing to
hallucinate.
"""

import csv
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from engine.predict import RecipientStats, enrich

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TXN_PATH = DATA_DIR / "transactions.csv"
MODEL = "gemini-flash-latest"  # gemini-2.5-flash (spec'd model) is no longer available to new API keys

_client = None
_all_raw_txns = None
_recipient_stats = None


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _load_raw_txns():
    with open(TXN_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [{
        "txn_id": r["txn_id"], "user_id": r["user_id"], "raw_description": r["raw_description"],
        "amount": float(r["amount"]), "currency": r["currency"], "timestamp": r["timestamp"],
        "channel": r["channel"], "counterparty_ref": r["counterparty_ref"],
    } for r in rows]


def _get_all_raw_txns():
    global _all_raw_txns, _recipient_stats
    if _all_raw_txns is None:
        _all_raw_txns = _load_raw_txns()
        _recipient_stats = RecipientStats.from_raw_txns(_all_raw_txns)
    return _all_raw_txns, _recipient_stats


def _enrich_user(user_id: str, month: str = None):
    """month: 'YYYY-MM', or None for the user's full history."""
    all_raw, stats = _get_all_raw_txns()
    user_raw = [t for t in all_raw if t["user_id"] == user_id]
    if month:
        user_raw = [t for t in user_raw if t["timestamp"].startswith(month)]
    return [enrich(t, recipient_stats=stats) for t in user_raw]


def _aggregate_by_category(enriched):
    agg = defaultdict(lambda: {"total": 0.0, "count": 0})
    for e in enriched:
        agg[e.category]["total"] += e.amount
        agg[e.category]["count"] += 1
    return dict(agg)


def _format_aggregate_lines(agg):
    return [f"- {cat}: {v['count']} عملية، صافي {v['total']:.2f} ريال"
            for cat, v in sorted(agg.items(), key=lambda kv: kv[1]["total"])]


def report(user_id: str, month: str) -> str:
    """month: 'YYYY-MM'. Returns a short Arabic markdown monthly report."""
    enriched = _enrich_user(user_id, month)
    agg = _aggregate_by_category(enriched)
    total_in = sum(v["total"] for v in agg.values() if v["total"] > 0)
    total_out = sum(v["total"] for v in agg.values() if v["total"] < 0)

    prompt = (
        "أنت مساعد مالي شخصي. اكتب تقريراً شهرياً موجزاً بالعربية (فقرة أو فقرتين ثم نقاط) "
        "بالاعتماد فقط على البيانات المجمّعة التالية. لا تخترع أي أرقام غير موجودة هنا.\n\n"
        f"الشهر: {month}\n"
        f"إجمالي الدخل: {total_in:.2f} ريال\n"
        f"إجمالي الصرف: {abs(total_out):.2f} ريال\n"
        "الصرف حسب الفئة:\n" + "\n".join(_format_aggregate_lines(agg))
    )
    resp = get_client().models.generate_content(model=MODEL, contents=prompt)
    return resp.text


def chat(user_id: str, message: str) -> str:
    """Answer a free-text question about the user's spending, in Arabic."""
    enriched = _enrich_user(user_id, month=None)
    agg = _aggregate_by_category(enriched)

    prompt = (
        "أنت مساعد مالي شخصي. أجب عن سؤال المستخدم بالعربية بإيجاز ودقة، "
        "بالاعتماد فقط على البيانات المجمّعة التالية. إن لم تكفِ البيانات للإجابة، قل ذلك بوضوح.\n\n"
        "بيانات الصرف حسب الفئة (كامل الفترة المتاحة):\n" + "\n".join(_format_aggregate_lines(agg)) +
        f"\n\nسؤال المستخدم: {message}"
    )
    resp = get_client().models.generate_content(model=MODEL, contents=prompt)
    return resp.text
