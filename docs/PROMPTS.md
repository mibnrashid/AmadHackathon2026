# PROMPTS — run these in Claude Code, in order

Rules for you: run **one prompt at a time**, check the output it shows you, and only move to the next when it looks right. If something's off, fix it in that step before continuing. All prompts assume `CLAUDE.md`, `docs/DATA_SPEC.md`, and `docs/ENGINE_SPEC.md` are in the repo.

---

### 0 — Scaffold
```
Read CLAUDE.md. Create the repo structure it describes (empty folders + a requirements.txt with the listed dependencies + a .gitignore for data/ and __pycache__). Don't write any logic yet. Show me the tree.
```

### 1 — Merchant catalog
```
Read docs/DATA_SPEC.md, section "Table 1". Write scripts/gen_merchants.py that generates data/merchants.csv. Use the seed merchants table verbatim as real anchors, then generate a plausible long tail up to ~500 total, keeping ~70% in_directory=true and a realistic category spread. Follow all CLAUDE.md rules (UTF-8, etc). Run it, then show me 15 random rows including at least 3 with Arabic names and 3 with in_directory=false.
```

### 2 — Users / personas
```
Read docs/DATA_SPEC.md, section "Table 2". Write scripts/gen_users.py that generates data/users.csv with ~150 users across the 6 persona archetypes, using their income/rent/subs/qattah/remittance rules. Recurring_subs must reference real merchant_ids from data/merchants.csv. Run it and show me one example user per persona.
```

### 3 — Transaction generator (the big one)
```
Read docs/DATA_SPEC.md fully. Write scripts/gen_transactions.py that generates data/transactions.csv (~30,000 rows) truth-first then corrupted, per the spec: INPUT columns + hidden answer-key columns, the corruption operators (recording corruption_ops), the 75/25 Arabic/Latin split with noise kept Latin, the transfer/ambiguity rules, the realistic distributions, recurring salary/rent/subs, unknown merchants, and ~2-3% garbage. Also emit data/golden_set.csv (~200 stratified rows, is_golden=true) and mark ~40 ambiguous rows mark_for_correction=true. Fix a random seed. 
After running, show me: 10 sample raw_descriptions with their true labels, the count by txn_type, the % in_directory, and 3 STC PAY rows that share the same raw string but have different true_intent.
```

### 4 — Layer 1: Clean
```
Read docs/ENGINE_SPEC.md, "Layer 1". Write engine/normalize.py (including the Arabic normalization) and engine/clean.py (exact → fuzzy with rapidfuzz → vector fallback with chromadb over the merchant catalog). Build the vector store from data/merchants.csv. Do NOT read any answer-key columns. 
Test it on 20 raw strings from data/transactions.csv (mix of known, unknown, and Arabic) and print raw → cleaned → matched merchant → resolved_by → confidence.
```

### 5 — Output schema + Layer 2: Predict
```
Read docs/ENGINE_SPEC.md, "Output model" and "Layer 2". Write engine/schema.py (the EnrichedTransaction Pydantic model) and engine/predict.py: category from merchant for purchases; context rules for transfers/income/cash; a corrections store (JSON file) that overrides predictions. Wire clean + predict into one function enrich(raw_txn) -> EnrichedTransaction. 
Test enrich() on 15 transactions including 3 ambiguous STC PAY ones, and show the full EnrichedTransaction JSON for each. Then simulate a correction on one and show it now returns resolved_by="correction".
```

### 6 — Layer 3: Explain (LLM)
```
Read docs/ENGINE_SPEC.md, "Layer 3". Write engine/explain.py using the google-genai SDK (model gemini-2.5-flash, key from .env via python-dotenv): report(user_id, month) and chat(user_id, message), both operating only on enriched transactions / aggregates, both replying in Arabic. Keep prompts tight. 
Test: generate a report for one user for one month, and answer "كم صرفت على المطاعم؟" for that user. Show both outputs. (The key is GEMINI_API_KEY in .env — see SETUP.md.)
```

### 7 — Eval
```
Read docs/ENGINE_SPEC.md, "Eval". Write eval/run_eval.py that runs the engine over data/transactions.csv, compares to the answer-key columns, and reports: deterministic_pct, merchant_accuracy, category_accuracy, intent_accuracy_ambiguous, avg latency_ms, and the token-cost multiplier vs raw→LLM. Print full-set and golden-set numbers separately, print a category confusion matrix, and write eval/metrics.json. 
Run it and show me the numbers.
```

### 8 — API
```
Read docs/ENGINE_SPEC.md, "API". Write api/main.py: a FastAPI app exposing /enrich, /correct, /report, /chat, /metrics exactly as specified, with CORS enabled. It should only call existing engine functions. 
Run it with uvicorn and show me example curl commands + responses for /enrich (with one ambiguous row) and /correct.
```

---

After step 7 you have the **real metrics** — hand those to whoever owns the deck to replace the placeholders. After step 8, Khalid's frontend can point at your local API instead of the sample JSON.
