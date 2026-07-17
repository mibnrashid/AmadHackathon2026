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

from engine.aggregate import build_dashboard
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


CHAT_SYSTEM_PROMPT = (
    "أنت مساعد مالي شخصي سعودي، ودود وخبير. تجيب فقط بالاعتماد على بيانات هذا المستخدم "
    "المرفقة أدناه -- لا تخترع أي فئة أو رقم أو تاجر غير موجود فيها، وإن لم تكفِ البيانات "
    "للإجابة قل ذلك بوضوح بدل التخمين. أجوبتك قصيرة ومحددة وبأرقام حقيقية من البيانات مباشرة. "
    "يمكنك الإجابة عن أي سؤال مالي شخصي: أين ذهبت الفلوس، الصرف في فئة أو تاجر معيّن، "
    "المقارنة بين فئتين أو بين شهرين، الاتجاهات، هل يقدر يتحمّل مصروفاً معيّناً، الميزانية، "
    "أو التوفير لتحقيق هدف. إذا سُئلت عن التوفير أو هدف مبلغ معيّن، اقترح تخفيضات محددة "
    "ومقدّرة بالريال من فئات إنفاق حقيقية تظهر في البيانات (مثلاً \"قلّل مطاعم بمقدار كذا\")، "
    "وليس نصائح عامة."
)


def _format_dashboard_context(dash: dict) -> str:
    u, t = dash["user"], dash["totals"]
    lines = [
        f"الشخصية: {u['persona']} | المدينة: {u['home_city']}",
        f"الدخل الشهري المصرّح به: {u['income_monthly']:.2f} ريال",
        f"الشهر المعروض: {dash['month']}",
        "",
        f"إجمالي الدخل هذا الشهر: {t['income']:.2f} ريال",
        f"إجمالي الصرف هذا الشهر: {t['spending']:.2f} ريال",
        f"الصافي: {t['net']:.2f} ريال | نسبة الادخار: {t['savings_rate'] * 100:.1f}%",
        "",
        "الصرف حسب الفئة (من الأعلى للأقل):",
    ]
    for c in dash["by_category"]:
        lines.append(f"- {c['label_ar']} ({c['category']}): {c['count']} عملية، "
                      f"{c['total']:.2f} ريال ({c['pct']:.1f}%)")

    lines.append("")
    lines.append("أكثر التجار صرفاً:")
    for m in dash["top_merchants"]:
        lines.append(f"- {m['name']}: {m['total']:.2f} ريال ({m['count']} عملية)")

    lines.append("")
    lines.append("أحدث العمليات:")
    recent = sorted(dash["transactions"], key=lambda e: e.timestamp, reverse=True)[:15]
    for e in recent:
        lines.append(f"- {e.timestamp.date()} | {e.display_name} | {e.category} | "
                      f"{e.amount:.2f} {e.currency}")

    return "\n".join(lines)


def chat(user_id: str, message: str, month: str = None) -> str:
    """Answer any personal-finance question about this user, in Arabic.
    month: 'YYYY-MM', or None for the user's latest available month --
    same aggregate view build_dashboard() gives the /dashboard endpoint."""
    dash = build_dashboard(user_id, month)
    context = _format_dashboard_context(dash)
    prompt = f"{CHAT_SYSTEM_PROMPT}\n\nبيانات المستخدم:\n{context}\n\nسؤال المستخدم: {message}"
    resp = get_client().models.generate_content(model=MODEL, contents=prompt)
    return resp.text
