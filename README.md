# Khawarizm — AI/Data Engine

A hackathon prototype that turns messy Saudi bank transaction strings (e.g. `SP *MCD_2938_RYD`) into clean, structured, categorized transactions, then uses an LLM to write a monthly report and answer budget questions in Arabic.

The thesis: **deterministic-first, LLM-last.** Regex/fuzzy/vector matching does the heavy lifting for free and instantly; the LLM only ever phrases already-structured aggregates into Arabic prose — it never categorizes and never sees a raw string. That's what keeps the system cheap, fast, and free of hallucination risk on the numbers.

Full specs live in `docs/DATA_SPEC.md` (dataset) and `docs/ENGINE_SPEC.md` (engine). Build order was `docs/PROMPTS.md`. This README is the "what actually got built and what it measures" summary.

---

## 1. Three-layer architecture

```
raw_description  ──▶  Layer 1: Clean   ──▶  Layer 2: Predict  ──▶  Layer 3: Explain
(dirty string)        exact → fuzzy →        category + intent      Gemini writes the
                       vector fallback        (rules, no ML)         Arabic report/chat
                       (merchant lookup)                              over AGGREGATES only
```

1. **Clean** (`engine/normalize.py`, `engine/clean.py`) — strip corruption noise, normalize Arabic, then resolve to a merchant via exact match → fuzzy match (rapidfuzz) → vector fallback (chromadb). Only for `pos`/`ecom`/`sadad` channels; transfers/income/cash skip this entirely (no merchant to look up).
2. **Predict** (`engine/schema.py`, `engine/predict.py`) — purchases inherit their category from the matched merchant; transfers/income/cash have no merchant, so a small set of transparent context rules (amount sign/size, time-of-day, day-of-month, recurring counterparty) infers the intent (gift / split / personal / remittance / bill / salary / topup). A JSON corrections store lets a user's manual correction override the prediction permanently.
3. **Explain** (`engine/explain.py`) — Gemini (`google-genai`) turns category-level aggregates (never raw transactions) into a short Arabic monthly report or answers a free-text question in Arabic.

Plus:
- **Eval** (`eval/run_eval.py`) — scores the whole engine against a hidden answer key.
- **API** (`api/main.py`) — thin FastAPI wrapper over the four functions above.

This is a prototype: local CSVs, in-memory logic, one small FastAPI app. No auth, no cloud DB, no Docker, no microservices.

---

## 2. Repo structure

```
CLAUDE.md                  project rules Claude Code reads on every prompt
README.md                  this file
requirements.txt           pandas, rapidfuzz, chromadb, pydantic, fastapi, uvicorn, google-genai, python-dotenv
.env                       GEMINI_API_KEY (gitignored)
.gitignore                 data/, __pycache__/, *.pyc, .env

docs/
  DATA_SPEC.md              synthetic dataset spec (merchants/users/transactions, corruption ops, ambiguity rules)
  ENGINE_SPEC.md            engine spec (3 layers, output model, eval, API)
  SETUP.md                  manual one-time setup (Gemini key, venv, .env)
  PROMPTS.md                the build-order prompt sequence used to build this repo
  Khawarizm_Engine_Contract_for_Khalid.md   (handoff/contract notes)

scripts/                    data generators (run in this order)
  gen_merchants.py           -> data/merchants.csv      (500 rows)
  gen_users.py                -> data/users.csv          (150 rows)
  gen_transactions.py        -> data/transactions.csv   (~31.5k rows) + data/golden_set.csv (~214 rows)

data/                        generated CSVs (gitignored) + corrections.json (learning-loop store)

engine/
  normalize.py                Arabic/corruption-noise normalization
  clean.py                    Layer 1: exact -> fuzzy -> vector merchant resolution
  schema.py                   EnrichedTransaction Pydantic v2 output contract
  predict.py                  Layer 2: category/intent rules + corrections store + enrich()
  aggregate.py                per-user dashboard aggregation (totals/by_category/top_merchants), shared by the API and Layer 3
  explain.py                  Layer 3: Gemini report()/chat()

eval/
  run_eval.py                 scores engine vs answer-key columns, writes metrics.json
  metrics.json                latest eval results (generated)
  metrics_old.json            pre-coverage-change eval results, kept for comparison (see README §6)

api/
  main.py                     FastAPI app: /enrich /correct /report /chat /metrics /user/{user_id}/dashboard
```

---

## 3. The dataset (`docs/DATA_SPEC.md`)

Everything is **generated truth-first, then corrupted** — the true merchant/category/intent is decided first, and the answer-key columns are built alongside the dirty string, never guessed after the fact. Fixed RNG seeds throughout (merchants=42, users=7, transactions=11) for full reproducibility. All CSVs are `utf-8-sig`.

### `data/merchants.csv` — 500 rows
- 35 **real seed merchants** used verbatim from the spec (McDonald's, Al Baik, STC, Panda, Careem, Netflix, SEC, Absher, Saudia, ...), expanded with a **curated brand long tail** (~100 more real/plausible Saudi/regional brands: Domino's, KFC, Lulu, Jarir-adjacent shopping brands, hospitals, telecoms, etc.) and a **procedurally generated long tail** (`{City} {Category noun}` combos, e.g. "Khobar Pharmacy", "Njran Foundation") to reach 500.
- **97.0% `in_directory=true`** (485/500) — updated from an earlier 70/30 split to match real-bank realism: a bank knows almost all of its own merchants. The remaining ~3% "new/unverified" merchants exist only so Layer 1's vector fallback still has something to catch occasionally.
- Every merchant carries **at least 3** (typically 6) `descriptor_patterns` (known dirty aliases Layer 1 can exact-match), and every alias — `name_en`, `name_ar`, and every pattern, across **all 500 merchants** — is guaranteed collision-free after normalization: generation walks candidate aliases in priority order (full name → compact form → `SP*` variant → word-initial abbreviation → truncation) and skips any candidate already claimed by a different merchant, rather than letting two merchants silently share one exact-index entry.
- Power-law-friendly: each merchant also carries `amount_mean/std`, `recurrence` (none/weekly/monthly), `aggregator` (e.g. some food merchants show wrapped via `JAHEZ`/`HUNGERSTATION`), and `cities`.
- Category spread across the 12 spending categories (of the 15 total keys — `transfer`/`income`/`cash` aren't merchant categories).

**Two bugs caught & fixed during generation:**
1. The procedural long tail's collision-handling originally disambiguated only the English name on a name clash, leaving ~180/500 merchants sharing an identical Arabic name with a sibling merchant. Fixed so both `name_en` and `name_ar` get the same disambiguating suffix.
2. Raising `in_directory` coverage to 97% surfaced a second, subtler collision: short derived aliases like a 4-letter truncation (`SAUD*`) or a word-initial abbreviation (`CC`) were sometimes shared by two *different* real brands (e.g. "Costa Coffee" and "Caribou Coffee" both abbreviate to `CC`; "Saudia", "Saudi German Hospital", and "Saudi Red Crescent" all truncate to `SAUD*`). Fixed by making pattern selection **skip** any candidate that collides with another merchant instead of keeping it — real brand names are left untouched, and the merchant just gets a slightly less punchy (but unique) alias in its place.

### `data/users.csv` — 150 rows
25 users per persona archetype (student, young_family, gig_worker, professional, retiree, business_owner), each following that persona's income/rent/subscription/qattah/remittance rules from the spec (e.g. students: family_support 1,500–2,500 SAR, ~85% do qattah, rarely have rent; business_owner: irregular business_revenue, counterparty kind `self`, supplier transfers). `recurring_subs` references real `merchant_id`s pulled only from monthly-recurring, `in_directory=true` merchants.

### `data/transactions.csv` — 30,035 rows + `data/golden_set.csv` — 214 rows
- **Mix:** purchase 24,678 (82%) · transfer 2,634 (9%) · income 1,821 (6%) · cash 902 (3%).
- **Merchant realism:** power-law weighted (a "top 20" of the real seed anchors get disproportionate purchase volume). Matching the merchant-directory change above, only **~2.7%** of identifiable purchases are now `in_directory=false` (down from ~10.8%), and only **~1.0%** of rows are pure garbage strings mapping to nothing (down from ~2.5%) — a bank sees almost all of its own merchants, so unknowns should be the exception, not a routine 1-in-10 event.
- **Corruption operators** (stacked probabilistically, recorded in `corruption_ops`): abbreviate, uppercase, space→symbol, prefix inject (`POS `, `SP *`, `MADA `, `APPLEPAY *`), id inject, city code, truncate, aggregator wrap, Arabic transliteration/noise (alef-variant swaps, tatweel insertion, tashkeel insertion, Arabic-Indic digits) — ~75/25 Latin/Arabic split, with injected noise (prefixes/ids/city codes) kept Latin even inside Arabic strings, matching real bank statements.
- **Ambiguous transfers (the thesis demo):** every transfer-type row shares a generic raw string (many literally the exact string `STC PAY TRANSFER`, spanning **all 7** intent labels) and only context (amount, day-of-month, time-of-day, recurring counterparty) determines `true_intent` ∈ {gift, split, personal, remittance, bill, salary, topup}. All transfer rows are flagged `is_ambiguous=true` by construction, since Layer 1 has no merchant to go on for them.
- `true_intent` distribution: personal 899 · bill 553 · gift 388 · split 418 · topup 236 · remittance 87 · salary 53.
- **Golden set** (`is_golden=true`, 214 rows): stratified across known/unknown merchants, every ambiguous intent type (≥12 each), Arabic descriptors, FX/USD rows, cash, income, and garbage.
- **Correction set:** 40 ambiguous rows flagged `mark_for_correction=true`, held out for the live-correction demo.

---

## 4. Non-negotiable rules (from `CLAUDE.md`)

1. UTF-8 everywhere — write `utf-8-sig`, dump JSON `ensure_ascii=False`.
2. Normalize Arabic before matching (unify alef `أإآ→ا`, `ى→ي`, strip tashkeel/tatweel, Arabic-Indic digits `٠-٩→0-9`).
3. Truth-first generation — decide the true label, then corrupt it.
4. **Never leak the answer key** — `engine/*.py` reads only INPUT columns; answer-key columns exist solely for `eval/run_eval.py`.
5. Deterministic-first, LLM-last — regex → exact → fuzzy → vector, only then (never per-transaction) the LLM.
6. Pydantic guards every output (`EnrichedTransaction`).
7. Test each piece before moving on.

---

## 5. Engine details

### Layer 1 — `engine/normalize.py` + `engine/clean.py`
`normalize()` strips known prefixes (including aggregator-app wraps like `JAHEZ*`, treated as noise just like `POS `/`SP *`), strips trailing id/city-code suffixes (looping until nothing more strips, since corruptions stack), then Arabic-normalizes and casefolds.

`clean(raw_description)` resolves in order:
1. **Exact** — normalized string hits a merchant's normalized name/alias/descriptor_pattern → `confidence≈0.97`.
2. **Fuzzy** (rapidfuzz `token_set_ratio`, threshold 85) over all known aliases.
3. **Vector** (chromadb, local ONNX MiniLM embeddings, cosine distance ≤0.60) — only for misses.

Only `in_directory=true` merchants are ever loaded into any of these three indices — unknown merchants are unknown by construction, so failing gracefully on them is correct behavior, not a bug. Results are cached (`_clean_cache`, plus a `warm_cache()` bulk pre-resolver that batches every vector-fallback lookup into as few chromadb calls as possible — this took a full eval run from ~6 hours to ~3 minutes).

### Output contract — `engine/schema.py`
`EnrichedTransaction` (Pydantic v2), matching `ENGINE_SPEC.md` exactly: `txn_id, raw_description, type, display_name, category, merchant{name,slug}, counterparty{label,kind}, amount, currency, timestamp, confidence, resolved_by, is_ambiguous`.

### Layer 2 — `engine/predict.py`
- Purchases: category = matched merchant's category, `display_name` = merchant name.
- Transfers/income/cash: no merchant, so context rules (reimplemented independently from the generator's own rules, using only INPUT-column signals — amount, timestamp, and a `RecipientStats` counterparty-recurrence tracker built only from `user_id`/`counterparty_ref`) infer `category` + `display_name` (`Salary`, `Rent / Bill`, `Remittance`, `Split`, `Food`, `Gift`, `Wallet Top-up`, or a generic `Transfer` fallback).
- **Corrections store** (`data/corrections.json`, keyed by `user_id` → `counterparty_ref` or normalized string) overrides the prediction, sets `resolved_by="correction"`, confidence `1.0`. This is the entire "learning loop" — no training, just an override table. Two demo corrections currently live in that file from earlier testing.
- `enrich(raw_txn, recipient_stats)` wires clean() + predict() + corrections into one call.

### Layer 3 — `engine/explain.py`
`report(user_id, month)` and `chat(user_id, message)` both enrich the user's transactions, aggregate by category (count + net amount), and hand only that aggregate to Gemini with a tight Arabic-only prompt. Both tested and return correct, well-grounded Arabic output (the chat function even explicitly said "the data has no 'restaurants' category, but here's 'food' which likely covers it" rather than guessing).

**Deviation from spec:** `ENGINE_SPEC.md` pins `gemini-2.5-flash`, but that model is now `404 — no longer available to new users` on this API key (Google has rolled the lineup forward since the spec was written). Swapped to `gemini-flash-latest`, the current recommended flash-tier alias — same free-tier intent, no other behavior change.

---

## 6. Eval results (`eval/run_eval.py` → `eval/metrics.json`)

Run over the full 30,035-row dataset and the 214-row golden set, **after** the 70%→97% `in_directory` coverage change above. `eval/metrics_old.json` keeps the pre-change numbers side by side for comparison.

| Metric | Full set — before (70%) | Full set — **after (97%)** | Golden set — after |
|---|---|---|---|
| `deterministic_pct` (no vector/LLM needed) | 87.06% | **93.99%** | 84.58% |
| `merchant_accuracy` — **known merchants only** | 88.41% (n=22,685) | **92.4%** (n=23,725) | 95.31% (n=64) |
| `merchant_accuracy` — blended incl. unknowns (kept for reference) | 78.9% | 90.6% (n=24,379) | 73.68% (n=95) |
| unknown-merchant graceful-decline rate | 54.96% (n=2,733) | 57.03% (n=654) | 51.61% (n=31) |
| `category_accuracy` | 87.8% (n=30,694) | **93.14%** (n=29,736) | 88.44% (n=199) |
| `intent_accuracy_ambiguous` (is_ambiguous rows only) | 90.31% (n=2,497) | 90.13% (n=2,634) | 89.29% (n=84) |
| `avg_deterministic_latency_ms` (cold, single live txn) | 45.15 ms | 118.23 ms | — |
| token-cost multiplier, naive raw→LLM vs. our aggregate-based approach | 86.1x | 86.1x | — |

`resolved_by` breakdown (full set, after): exact 21,793 · rules 5,357 · vector 1,804 · fuzzy 1,081.

A 15×15 category confusion matrix is also written into `metrics.json`.

**What moved, and why:**
- **`merchant_accuracy` (known-only) and `category_accuracy` both jumped several points.** Expected: with 485/500 merchants now in Layer 1's directory instead of 350/500, far more purchases resolve via cheap, high-confidence `exact`/`fuzzy` matches instead of falling through to the noisier vector fallback — `deterministic_pct` rose from 87% to 94% and vector-fallback volume dropped from 4,072 to 1,804 rows even though the dataset is only slightly smaller.
- **`avg_deterministic_latency_ms` went up (45ms → 118ms), not down.** This is a real, expected trade-off, not a regression: rapidfuzz's fuzzy step scores every known alias, and the directory now holds ~485 merchants × ~6 aliases each (guaranteed-unique, so none were dropped) versus a smaller, patchier alias set before. A bigger, cleaner directory costs more per fuzzy lookup — still well under 150ms per transaction, fine for this prototype's use case.
- **Unknown-merchant graceful-decline rate barely moved (~55%→57%)** and its sample size shrank a lot (2,733→654 rows), matching the ~3% unknown-merchant target. This confirms it's a property of `FUZZY_THRESHOLD`/`VECTOR_MAX_DISTANCE` in `engine/clean.py`, not of how many unknowns exist in the data — still flagged as the natural next tuning step, not yet done.

---

## 7. API (`api/main.py`)

FastAPI, CORS enabled, only calls the functions above. Verified live via `uvicorn api.main:app --port 8000`:

- `POST /enrich` — `{transactions:[RawTxn]}` → `{transactions:[EnrichedTransaction]}`. Tested with one ambiguous STC PAY transfer + one known-merchant purchase; both enriched correctly.
- `POST /correct` — `{txn_id, category, display_name}` → updated `EnrichedTransaction` with `resolved_by="correction"`. Verified the correction **persists**: re-`/enrich`-ing the same `txn_id` afterwards still returns the corrected value.
- `POST /report` — `{user_id, month}` → `{report_markdown}` (Arabic).
- `POST /chat` — `{user_id, message, month?}` → `{answer}` (Arabic). Now a general finance assistant grounded in the same aggregate the dashboard shows — see §11 below.
- `GET /user/{user_id}/dashboard?month=YYYY-MM` — the per-user spending dashboard (income/spending/net/savings, category breakdown, top merchants, enriched transactions). `month` optional, defaults to the user's latest available month. See §11 below.
- `GET /metrics` → contents of `eval/metrics.json` (404s cleanly if eval hasn't been run yet).

---

## 8. Running it end-to-end

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# .env must contain GEMINI_API_KEY=... (see docs/SETUP.md)

# 1. Generate the dataset (order matters -- each script reads the previous one's output)
python scripts/gen_merchants.py
python scripts/gen_users.py
python scripts/gen_transactions.py

# 2. Score the engine
python eval/run_eval.py

# 3. Serve the API
uvicorn api.main:app --reload
```

---

## 9. Tech stack

Python 3.13 (3.11+ required) · pandas · rapidfuzz · chromadb (local ONNX MiniLM embeddings, downloaded once to `~/.cache/chroma`) · pydantic v2 · fastapi + uvicorn · google-genai (`gemini-flash-latest`) · python-dotenv.

---

## 10. Status

Everything in `docs/PROMPTS.md`'s build order is done: data generation (3 scripts + golden set), all 3 engine layers, the corrections/learning loop, eval with real numbers, a working API, a per-user dashboard endpoint, and a general-purpose Arabic finance-assistant chat — all individually tested against real data, not just imported and assumed to work. `data/corrections.json` is a clean `{}` (the 2 demo corrections from earlier testing were cleared). Known follow-ups, in rough priority order:
- Tighten `FUZZY_THRESHOLD`/`VECTOR_MAX_DISTANCE` to improve the unknown-merchant graceful-decline rate (currently ~57%).
- Build an actual UI against `/user/{user_id}/dashboard` and `/chat` — see §11 for how.

**Locked-in demo user:** `U0023` (student, home city MAD). Their latest month (2026-06) tells a clean, relatable story: 32 transactions, food is the clear #1 category (676.32 SAR / 31.6%, 16 transactions across Herfy/Kudu/HungerStation), transport #2 (Uber, 383.09 SAR), essentially break-even (net −51.05 SAR, savings rate −2.4%). Good spread of merchants, no single outlier transaction dominating the story artificially.

---

## 11. Frontend integration guide

Two endpoints exist specifically for the frontend to build a personal-finance UI on top of: **`GET /user/{user_id}/dashboard`** (structured numbers for charts/summary cards) and **`POST /chat`** (free-text Arabic Q&A grounded in that same data). Both are read-only from the frontend's perspective — they compute everything live from `data/transactions.csv` + `data/users.csv` on each call, there's nothing to "load" or "sync" first beyond having run the data-generation scripts once (§8).

### Why these two exist
The dashboard endpoint answers "show me my money, visually." The chat endpoint answers "let me ask about my money in my own words." Both are built from the exact same aggregate (`engine/aggregate.py::build_dashboard()`), so **the chatbot can never contradict the dashboard** — if the UI shows food at 676.32 SAR, the chatbot will cite that same number, not a different one it computed separately.

### `GET /user/{user_id}/dashboard?month=YYYY-MM`
`month` is optional — omit it to get the user's most recent month with data. Response shape:

```jsonc
{
  "user": { "user_id": "U0023", "persona": "student", "income_monthly": 2201.49, "home_city": "MAD" },
  "month": "2026-06",
  "totals": { "income": 2091.48, "spending": 2142.53, "net": -51.05, "savings_rate": -0.0244 },
  "by_category": [
    { "category": "food", "label_ar": "طعام ومطاعم", "count": 16, "total": 676.32, "pct": 31.6 },
    // ... sorted high to low by total, spending categories only
  ],
  "top_merchants": [
    { "name": "Uber", "slug": "uber", "total": 309.32, "count": 2 },
    // ... up to 8, spending only, sorted high to low
  ],
  "transactions": [ /* full EnrichedTransaction[] for that month, see engine/schema.py */ ]
}
```

Build with this: `totals` → 3-4 summary cards (income/spending/net, with `savings_rate` as a %). `by_category` → a bar/donut chart, `label_ar` is ready-to-render Arabic (no lookup table needed on the frontend). `top_merchants` → a "where your money went" list, `slug` is stable and safe to use as a React key or for merchant icons. `transactions` → a scrollable transaction list/table if you want one; each item is the same `EnrichedTransaction` shape `/enrich` returns, so any component built for one works for the other.

### `POST /chat`
```jsonc
// request
{ "user_id": "U0023", "message": "وش أكثر شي صرفت عليه هذا الشهر؟", "month": "2026-06" /* optional */ }
// response
{ "answer": "أكثر فئة صرفت عليها هذا الشهر هي **طعام ومطاعم (food)** بإجمالي **676.32 ريال**..." }
```
This is a general assistant, not a single-purpose "savings bot" — it was tested against three different question types on `U0023` and answered all three correctly, grounded in real figures:
1. *"وش أكثر شي صرفت عليه هذا الشهر؟"* (what did I spend most on?) → named `food`, cited 676.32 SAR / 31.6% / 16 transactions, and named `Uber` as the top single merchant.
2. *"كم صرفت في المطاعم مقارنة بالبقالة؟"* (food vs. groceries?) → compared 676.32 SAR vs 175.20 SAR and stated the exact 501.12 SAR gap.
3. *"أبغى أوفر ٥٠٠ ريال، من وين أقلّل؟"* (I want to save 500 SAR, where from?) → gave a concrete, additive plan citing real merchants: −250 SAR from food (naming Herfy/HungerStation specifically), −150 SAR from Uber, −100 SAR from shopping (naming Jed Boutique) — summing to exactly 500.

Frontend-wise: render `answer` as Markdown (the model returns `**bold**` for figures/categories — that's intentional, not an accident to strip out). The reply is always in Arabic; there's no language-switching to design around. Pass `month` through if the user is looking at a specific month on the dashboard, so the chatbot answers about *that* month rather than defaulting to the latest one.

### Rules baked into the assistant (so the frontend doesn't need to re-guard against them)
- It only cites categories/merchants/numbers that exist in that user's real data — it will not invent a category the data doesn't have.
- If asked something the data genuinely can't answer, it says so rather than guessing.
- Savings/goal questions always get a quantified per-category breakdown (real SAR amounts, real merchant names), never generic advice like "cook at home more."
