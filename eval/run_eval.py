"""Run the engine over data/transactions.csv and score it against the
answer-key columns. This script is the ONE place allowed to read those
columns (CLAUDE.md rule 4) -- engine/*.py never does.

Writes eval/metrics.json and prints full-set + golden-set numbers plus a
category confusion matrix.
"""

import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.clean import _clean_cache, clean, warm_cache
from engine.predict import RecipientStats, enrich

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TXN_PATH = DATA_DIR / "transactions.csv"
METRICS_PATH = Path(__file__).resolve().parent / "metrics.json"

CATEGORIES = ["food", "groceries", "transport", "shopping", "bills", "telecom", "health",
              "entertainment", "travel", "education", "government", "charity",
              "transfer", "income", "cash"]

NAIVE_PROMPT_TEMPLATE = (
    "Classify this bank transaction into one of: " + ", ".join(CATEGORIES) + ". "
    "Identify the merchant if any. Transaction: '{raw}'. "
    'Respond as JSON: {{"merchant": ..., "category": ...}}'
)
NAIVE_RESPONSE_TOKENS = 20  # rough size of a short JSON classification reply

# Maps Layer 2's rule-based display_name back to the DATA_SPEC intent vocabulary,
# purely so this eval script can score against true_intent -- predict.py itself
# never sees or needs true_intent.
DISPLAY_TO_INTENT = {
    "Rent / Bill": "bill", "Gift": "gift", "Split": "split", "Salary": "salary",
    "Remittance": "remittance", "Food": "personal", "Wallet Top-up": "topup",
}

AVG_TXNS_PER_REPORT_BATCH = 200  # ~ one user-month, matches gen_transactions.py's per-user target


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def load_rows():
    with open(TXN_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_raw_txn(r):
    return {
        "txn_id": r["txn_id"], "user_id": r["user_id"], "raw_description": r["raw_description"],
        "amount": float(r["amount"]), "currency": r["currency"], "timestamp": r["timestamp"],
        "channel": r["channel"], "counterparty_ref": r["counterparty_ref"],
    }


def measure_cold_latency(rows, sample_size=300, seed=1):
    """Avg time for the deterministic (exact/fuzzy) path on a COLD cache --
    representative of a live single-transaction API call. Must run before
    warm_cache(), which turns every subsequent clean() call for these rows
    into a cache hit and would otherwise make this measurement meaningless."""
    candidates = list({r["raw_description"] for r in rows
                        if r["channel"] in ("pos", "ecom", "sadad") and r["is_in_directory"] == "True"})
    sample = random.Random(seed).sample(candidates, min(sample_size, len(candidates)))
    latencies = []
    for raw in sample:
        _clean_cache.pop(raw, None)
        t0 = time.perf_counter()
        result = clean(raw)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if result["resolved_by"] in ("exact", "fuzzy"):
            latencies.append(elapsed_ms)
    return round(sum(latencies) / len(latencies), 4) if latencies else None


def evaluate(rows, stats, label):
    n = len(rows)
    resolved_by_counts = Counter()
    merchant_correct = merchant_total = 0
    # Known (in_directory=True) merchants SHOULD be matched; unknown ones
    # SHOULD gracefully return no merchant -- blending both into one number
    # makes correct "I don't know this one" behavior look like an error.
    known_merchant_correct = known_merchant_total = 0
    unknown_correctly_declined = unknown_total = 0
    category_correct = category_total = 0
    intent_correct = intent_total = 0
    confusion = defaultdict(Counter)

    for r in rows:
        txn = to_raw_txn(r)
        enriched = enrich(txn, recipient_stats=stats)

        resolved_by_counts[enriched.resolved_by] += 1

        true_category = r["true_category"]
        if true_category:
            category_total += 1
            confusion[true_category][enriched.category] += 1
            if enriched.category == true_category:
                category_correct += 1

        if r["txn_type"] == "purchase" and r["true_merchant_id"]:
            merchant_total += 1
            is_correct_match = bool(enriched.merchant and enriched.merchant.name == r["true_merchant_name"])
            if is_correct_match:
                merchant_correct += 1
            if r["is_in_directory"] == "True":
                known_merchant_total += 1
                if is_correct_match:
                    known_merchant_correct += 1
            else:
                unknown_total += 1
                if enriched.merchant is None:
                    unknown_correctly_declined += 1

        if r["is_ambiguous"] == "True":
            intent_total += 1
            predicted_intent = DISPLAY_TO_INTENT.get(enriched.display_name)
            if predicted_intent == r["true_intent"]:
                intent_correct += 1

    total_resolved = sum(resolved_by_counts.values())
    deterministic = (resolved_by_counts["exact"] + resolved_by_counts["fuzzy"]
                      + resolved_by_counts["rules"] + resolved_by_counts["correction"])

    return {
        "label": label,
        "n_rows": n,
        "deterministic_pct": round(100 * deterministic / total_resolved, 2) if total_resolved else 0,
        "resolved_by_counts": dict(resolved_by_counts),
        "merchant_accuracy": round(100 * merchant_correct / merchant_total, 2) if merchant_total else None,
        "merchant_accuracy_n": merchant_total,
        "merchant_accuracy_known_only": (round(100 * known_merchant_correct / known_merchant_total, 2)
                                          if known_merchant_total else None),
        "merchant_accuracy_known_only_n": known_merchant_total,
        "unknown_merchant_graceful_decline_pct": (round(100 * unknown_correctly_declined / unknown_total, 2)
                                                   if unknown_total else None),
        "unknown_merchant_graceful_decline_n": unknown_total,
        "category_accuracy": round(100 * category_correct / category_total, 2) if category_total else None,
        "category_accuracy_n": category_total,
        "intent_accuracy_ambiguous": round(100 * intent_correct / intent_total, 2) if intent_total else None,
        "intent_accuracy_ambiguous_n": intent_total,
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
    }


def compute_token_cost(rows):
    raws = [r["raw_description"] for r in rows]
    naive_tokens = sum(estimate_tokens(NAIVE_PROMPT_TEMPLATE.format(raw=raw)) + NAIVE_RESPONSE_TOKENS for raw in raws)

    # Our approach spends 0 LLM tokens classifying (Layers 1-2 are deterministic
    # rules, no model call). The only LLM usage anywhere in the system is the
    # Layer-3 aggregate report/chat, amortized over the transactions it covers.
    sample_aggregate_lines = "\n".join(f"- {c}: 12 عملية، صافي -450.00 ريال" for c in CATEGORIES[:10])
    report_prompt_tokens = estimate_tokens(sample_aggregate_lines) + 120  # + fixed instruction overhead
    our_tokens_amortized = report_prompt_tokens / AVG_TXNS_PER_REPORT_BATCH * len(raws)

    return {
        "naive_raw_to_llm_tokens": naive_tokens,
        "our_amortized_tokens": round(our_tokens_amortized, 1),
        "multiplier": round(naive_tokens / our_tokens_amortized, 1) if our_tokens_amortized else None,
    }


def print_confusion_matrix(confusion):
    cats = sorted(set(confusion) | {c for v in confusion.values() for c in v})
    header = "true\\pred".ljust(14) + "".join(c[:8].rjust(9) for c in cats)
    print(header)
    for true_cat in cats:
        row = confusion.get(true_cat, {})
        print(true_cat.ljust(14) + "".join(str(row.get(c, 0)).rjust(9) for c in cats))


def main():
    rows = load_rows()
    raw_txns = [to_raw_txn(r) for r in rows]
    stats = RecipientStats.from_raw_txns(raw_txns)
    golden_rows = [r for r in rows if r["is_golden"] == "True"]

    print("Measuring cold-path (single live transaction) latency...")
    latency_ms = measure_cold_latency(rows)

    purchase_raws = [r["raw_description"] for r in rows if r["channel"] in ("pos", "ecom", "sadad")]
    print(f"Warming merchant-resolution cache ({len(set(purchase_raws))} unique purchase strings)...")
    t0 = time.time()
    warm_cache(purchase_raws)
    print(f"  done in {time.time() - t0:.1f}s")

    print(f"Evaluating full set ({len(rows)} rows)...")
    t0 = time.time()
    full_metrics = evaluate(rows, stats, "full_set")
    print(f"  done in {time.time() - t0:.1f}s")

    print(f"Evaluating golden set ({len(golden_rows)} rows)...")
    golden_metrics = evaluate(golden_rows, stats, "golden_set")

    token_cost = compute_token_cost(rows)

    result = {"avg_deterministic_latency_ms": latency_ms, "full_set": full_metrics,
              "golden_set": golden_metrics, "token_cost": token_cost}
    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\navg_deterministic_latency_ms (cold, single live transaction): {latency_ms}")
    for label, metrics in (("FULL SET", full_metrics), ("GOLDEN SET", golden_metrics)):
        print(f"\n=== {label} (n={metrics['n_rows']}) ===")
        print(f"deterministic_pct: {metrics['deterministic_pct']}%")
        print(f"merchant_accuracy (blended): {metrics['merchant_accuracy']}% (n={metrics['merchant_accuracy_n']})")
        print(f"merchant_accuracy (known merchants only): {metrics['merchant_accuracy_known_only']}% "
              f"(n={metrics['merchant_accuracy_known_only_n']})")
        print(f"unknown_merchant_graceful_decline_pct: {metrics['unknown_merchant_graceful_decline_pct']}% "
              f"(n={metrics['unknown_merchant_graceful_decline_n']})")
        print(f"category_accuracy: {metrics['category_accuracy']}% (n={metrics['category_accuracy_n']})")
        print(f"intent_accuracy_ambiguous: {metrics['intent_accuracy_ambiguous']}% (n={metrics['intent_accuracy_ambiguous_n']})")
        print("resolved_by counts:", metrics["resolved_by_counts"])

    print("\n=== Category confusion matrix (full set) ===")
    print_confusion_matrix(full_metrics["confusion_matrix"])

    print("\n=== Token cost: naive raw->LLM vs our aggregate-based approach ===")
    print(token_cost)

    print(f"\nWrote {METRICS_PATH}")


if __name__ == "__main__":
    main()
