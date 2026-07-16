# ENGINE_SPEC — the three layers + eval + API

The engine reads only the INPUT columns (CLAUDE.md rule 4) and returns validated `EnrichedTransaction` objects.

---

## Output model — `EnrichedTransaction` (Pydantic v2)

This is the contract with the frontend. Match it exactly.

```
txn_id: str
raw_description: str
type: Literal["purchase","transfer","income","cash"]
display_name: str                       # clean UI title: "McDonald's" / "Gift" / "Salary"
category: str                           # one of the 15 keys
merchant: Optional[{name: str, slug: str}]        # set when type == purchase
counterparty: Optional[{label: str, kind: Literal["person","business","wallet","self"]}]  # transfer/income
amount: float                           # signed
currency: str
timestamp: datetime
confidence: float                       # 0–1
resolved_by: Literal["exact","fuzzy","vector","rules","correction"]
is_ambiguous: bool
```

`slug` = lowercase merchant name, no spaces (`"McDonald's"` → `"mcdonalds"`) — the frontend maps it to a logo.

---

## Layer 1 — Clean (`engine/normalize.py`, `engine/clean.py`)

1. **normalize(raw)** → cleaned string: strip prefixes (`POS`, `SP *`, `MADA`, `APPLEPAY *`), terminal/ref ids (`_2938`, `#48213`), city codes, symbols. Then **Arabic-normalize**: unify alef `أإآ→ا`, `ى→ي`, strip tashkeel + tatweel `ـ`, Arabic-Indic digits `٠-٩→0-9`, collapse whitespace, casefold.
2. **exact lookup** — normalized string / any descriptor_pattern hits a merchant → `resolved_by="exact"`, confidence ~0.97.
3. **fuzzy** (rapidfuzz, token_set_ratio) over merchant names + patterns; accept above a threshold (~85) → `resolved_by="fuzzy"`, confidence = score/100.
4. **vector fallback** (chromadb) — only for misses: embed the cleaned string, search a small store built from the merchant catalog, take nearest if above threshold → `resolved_by="vector"`. If still nothing → merchant `null`, low confidence.

Transfers/income/cash (by `channel`) skip merchant lookup and go straight to Layer 2.

---

## Layer 2 — Predict (`engine/predict.py`)

- **Purchases:** category comes from the matched merchant's category. `type="purchase"`, `display_name = merchant name`.
- **Transfers/income/cash:** no merchant → apply the context rules from DATA_SPEC (amount sign/size, time-of-day, day-of-month, recurring recipient) to pick `category` + a `display_name` ("Gift", "Salary", "Cash withdrawal"). Set `is_ambiguous=true` where context is the only signal.
- **Corrections store:** a small JSON/dict keyed by (user_id, normalized_string or counterparty_ref). If a correction exists, it overrides the prediction and sets `resolved_by="correction"`, confidence 1.0. This is what makes the STC Pay demo "stick".

Keep Layer 2 as transparent rules for the prototype — no training. The learning loop = corrections feeding this store.

---

## Layer 3 — Explain (`engine/explain.py`, google-genai / Gemini)

Input is always clean `EnrichedTransaction[]` — never raw strings. Use the `google-genai` SDK with model `gemini-2.5-flash`; load `GEMINI_API_KEY` from `.env` via `python-dotenv`. See SETUP.md.

- **report(user_id, month)** → group the user's clean transactions by category, compute totals, pass the *aggregates* (not raw text) to the LLM, ask for a short Arabic monthly report. Return markdown.
- **chat(user_id, message)** → pass the user's clean transactions (or pre-computed aggregates) + the question, answer in Arabic.

Keep prompts tight; the data is already structured, so the LLM only phrases — it never categorizes. This is why token cost is tiny and there's nothing to hallucinate.

---

## Eval (`eval/run_eval.py`)

Run the engine over `transactions.csv`, compare to the answer-key columns, print a table and write `metrics.json`:

- **deterministic_pct** — % resolved by exact+fuzzy with no vector/LLM call (the ~94% headline).
- **merchant_accuracy** — predicted merchant == true_merchant (purchases).
- **category_accuracy** — overall.
- **intent_accuracy_ambiguous** — accuracy on `is_ambiguous=true` rows only (proves Layer 2 earns its keep).
- **latency_ms** — avg deterministic-path time.
- **token_cost** — tokens if raw→LLM vs our clean approach; report the multiplier.
- **confusion_matrix** — category predicted vs true.

Report golden-set numbers separately from full-set numbers. **These outputs replace the placeholder metrics in the pitch deck** — use the real ones.

---

## API (`api/main.py`, FastAPI — thin wrapper over the functions above)

- `POST /enrich` — `{transactions:[RawTxn]}` → `{transactions:[EnrichedTransaction]}`
- `POST /correct` — `{txn_id, category, display_name}` → updated `EnrichedTransaction` (writes to corrections store)
- `POST /report` — `{user_id, month}` → `{report_markdown}`
- `POST /chat` — `{user_id, message}` → `{answer}`
- `GET /metrics` → `metrics.json`

Enable CORS for the frontend. This file should be ~40–60 lines — it only calls existing functions.
