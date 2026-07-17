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
  explain.py                  Layer 3: Gemini report()/chat()

eval/
  run_eval.py                 scores engine vs answer-key columns, writes metrics.json
  metrics.json                latest eval results (generated)

api/
  main.py                     FastAPI app: /enrich /correct /report /chat /metrics
```

---

## 3. The dataset (`docs/DATA_SPEC.md`)

Everything is **generated truth-first, then corrupted** — the true merchant/category/intent is decided first, and the answer-key columns are built alongside the dirty string, never guessed after the fact. Fixed RNG seeds throughout (merchants=42, users=7, transactions=11) for full reproducibility. All CSVs are `utf-8-sig`.

### `data/merchants.csv` — 500 rows
- 35 **real seed merchants** used verbatim from the spec (McDonald's, Al Baik, STC, Panda, Careem, Netflix, SEC, Absher, Saudia, ...), expanded with a **curated brand long tail** (~100 more real/plausible Saudi/regional brands: Domino's, KFC, Lulu, Jarir-adjacent shopping brands, hospitals, telecoms, etc.) and a **procedurally generated long tail** (`{City} {Category noun}` combos, e.g. "Khobar Pharmacy", "Njran Foundation") to reach 500.
- **70.0% `in_directory=true`** exactly (350/500) — the 30% "false" merchants are real (have a true category/name) but deliberately excluded from Layer 1's index, to exercise graceful degradation on genuinely unknown merchants.
- Power-law-friendly: each merchant carries `descriptor_patterns` (known dirty aliases Layer 1 can exact-match), `amount_mean/std`, `recurrence` (none/weekly/monthly), `aggregator` (e.g. some food merchants show wrapped via `JAHEZ`/`HUNGERSTATION`), and `cities`.
- Category spread across the 12 spending categories (of the 15 total keys — `transfer`/`income`/`cash` aren't merchant categories).

**Bug caught & fixed during generation:** the procedural long tail's collision-handling originally disambiguated only the English name on a name clash, leaving ~180/500 merchants sharing an identical Arabic name with a sibling merchant (e.g. two different "مول جدة"). Fixed so both `name_en` and `name_ar` get the same disambiguating suffix.

### `data/users.csv` — 150 rows
25 users per persona archetype (student, young_family, gig_worker, professional, retiree, business_owner), each following that persona's income/rent/subscription/qattah/remittance rules from the spec (e.g. students: family_support 1,500–2,500 SAR, ~85% do qattah, rarely have rent; business_owner: irregular business_revenue, counterparty kind `self`, supplier transfers). `recurring_subs` references real `merchant_id`s pulled only from monthly-recurring, `in_directory=true` merchants.

### `data/transactions.csv` — 31,476 rows + `data/golden_set.csv` — 214 rows
- **Mix:** purchase 26,200 (83%) · transfer 2,497 (8%) · income 1,834 (6%) · cash 945 (3%).
- **Merchant realism:** power-law weighted (a "top 20" of the real seed anchors get disproportionate purchase volume), ~10.8% of identifiable purchases are `in_directory=false` (unknown-merchant test bed), ~2.5% are pure garbage strings mapping to nothing.
- **Corruption operators** (stacked probabilistically, recorded in `corruption_ops`): abbreviate, uppercase, space→symbol, prefix inject (`POS `, `SP *`, `MADA `, `APPLEPAY *`), id inject, city code, truncate, aggregator wrap, Arabic transliteration/noise (alef-variant swaps, tatweel insertion, tashkeel insertion, Arabic-Indic digits) — ~75/25 Latin/Arabic split, with injected noise (prefixes/ids/city codes) kept Latin even inside Arabic strings, matching real bank statements.
- **Ambiguous transfers (the thesis demo):** every transfer-type row shares a generic raw string (many literally the exact string `STC PAY TRANSFER` — 1,238 rows in the dataset, spanning **all 7** intent labels) and only context (amount, day-of-month, time-of-day, recurring counterparty) determines `true_intent` ∈ {gift, split, personal, remittance, bill, salary, topup}. All transfer rows are flagged `is_ambiguous=true` by construction, since Layer 1 has no merchant to go on for them.
- `true_intent` distribution: personal 860 · bill 559 · gift 399 · split 350 · topup 212 · remittance 64 · salary 53.
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

Run over the full 31,476-row dataset and the 214-row golden set. **These are the real, current numbers** — not placeholders.

| Metric | Full set (n=31,476) | Golden set (n=214) |
|---|---|---|
| `deterministic_pct` (no vector/LLM needed) | 87.06% | 85.05% |
| `merchant_accuracy` — **known merchants only** | **88.41%** (n=22,685) | 93.85% (n=65) |
| `merchant_accuracy` — blended incl. unknowns (misleading, kept for reference) | 78.9% | 64.21% |
| unknown-merchant graceful-decline rate | 54.96% (n=2,733) | 43.33% (n=30) |
| `category_accuracy` | 87.8% (n=30,694) | 88.44% (n=199) |
| `intent_accuracy_ambiguous` (is_ambiguous rows only) | 90.31% (n=2,497) | 95.24% (n=84) |
| `avg_deterministic_latency_ms` (cold, single live txn) | 45.15 ms | — |
| token-cost multiplier, naive raw→LLM vs. our aggregate-based approach | 86.1x | — |

`resolved_by` breakdown (full set): exact 20,589 · rules 5,271 · vector 4,072 · fuzzy 1,539 · correction 5.

A 15×15 category confusion matrix is also written into `metrics.json`.

**Two honest findings surfaced by this eval, not yet acted on:**
1. **`merchant_accuracy` needed splitting.** The naive single number (78.9%) conflates two very different things: genuinely misidentifying a known merchant, and *correctly* declining to guess an unknown one. Split into "known merchants only" (88.41% — the real headline) and a separate "graceful decline rate" for unknowns.
2. **Unknown-merchant graceful-decline rate is only ~55%.** Meaning nearly half the time, an unknown merchant's corrupted string gets fuzzy/vector-matched to some *other*, similarly-named known merchant instead of correctly returning "no match." This points to `FUZZY_THRESHOLD` (85) and/or `VECTOR_MAX_DISTANCE` (0.60) in `engine/clean.py` being a bit permissive. Tightening them would likely trade off against known-merchant recall — flagged as the natural next tuning step, not yet done.

A related, structural cause: some procedurally-generated merchant names are near-duplicates by design (e.g. "Hail Supermarket" vs. "Hail Supermarket 74", created by the collision-suffix logic in `gen_merchants.py`) — fuzzy/vector matching can't always tell these apart, which is a realistic limitation, not an engine bug.

---

## 7. API (`api/main.py`)

FastAPI, CORS enabled, ~85 lines, only calls the functions above. Verified live via `uvicorn api.main:app --port 8000`:

- `POST /enrich` — `{transactions:[RawTxn]}` → `{transactions:[EnrichedTransaction]}`. Tested with one ambiguous STC PAY transfer + one known-merchant purchase; both enriched correctly.
- `POST /correct` — `{txn_id, category, display_name}` → updated `EnrichedTransaction` with `resolved_by="correction"`. Verified the correction **persists**: re-`/enrich`-ing the same `txn_id` afterwards still returns the corrected value.
- `POST /report` — `{user_id, month}` → `{report_markdown}` (Arabic).
- `POST /chat` — `{user_id, message}` → `{answer}` (Arabic).
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

Everything in `docs/PROMPTS.md`'s build order is done: data generation (3 scripts + golden set), all 3 engine layers, the corrections/learning loop, eval with real numbers, and a working API — all individually tested against real data, not just imported and assumed to work. Known follow-ups, in rough priority order:
- Tighten `FUZZY_THRESHOLD`/`VECTOR_MAX_DISTANCE` to improve the unknown-merchant graceful-decline rate (currently ~55%).
- Consider a frontend to actually exercise `/enrich`, `/correct`, `/report`, `/chat` visually.
- `data/corrections.json` currently has 2 demo corrections left over from testing (`U0082`, `U0061`) — harmless, but worth clearing before a clean demo run if you want a pristine corrections store.
