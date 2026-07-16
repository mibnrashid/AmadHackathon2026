# Khawarizm — AI/Data Engine (project context)

> Place this file at the repo root. Claude Code reads it automatically on every prompt.
> Detailed specs live in `docs/DATA_SPEC.md` and `docs/ENGINE_SPEC.md`. Build order is in `docs/PROMPTS.md`.

## What we're building

A hackathon prototype that turns messy Saudi bank transaction strings (e.g. `SP *MCD_2938_RYD`) into clean, structured, categorized transactions, then uses an LLM to write a monthly report and answer budget questions. Three layers:

1. **Clean** — regex + Arabic normalization → merchant lookup (exact → fuzzy → vector fallback).
2. **Predict** — assign a category; resolve ambiguous cases (STC Pay, transfers) with context rules; remember user corrections.
3. **Explain** — send only clean, validated JSON to the LLM for the report + chat.

This is a **prototype**, not production. Keep it simple: local CSVs, in-memory logic, one small FastAPI app. No auth, no cloud DB, no Docker, no microservices.

## Repo structure

```
CLAUDE.md
docs/            DATA_SPEC.md, ENGINE_SPEC.md, PROMPTS.md
data/            merchants.csv, users.csv, transactions.csv, golden_set.csv   (generated)
scripts/         gen_merchants.py, gen_users.py, gen_transactions.py
engine/          normalize.py, clean.py, predict.py, explain.py, schema.py
eval/            run_eval.py, metrics.json
api/             main.py   (FastAPI)
```

## Non-negotiable rules (these prevent the bugs that kill the demo)

1. **UTF-8 everywhere.** Write CSVs with `encoding="utf-8-sig"`, read with `utf-8`. Dump JSON with `ensure_ascii=False`. We have Arabic text; wrong encoding silently corrupts it.
2. **Normalize Arabic before matching** (see DATA_SPEC): unify alef `أإآ→ا`, `ى→ي`, strip tashkeel + tatweel, convert Arabic-Indic digits `٠-٩→0-9`. Without this, Arabic fuzzy matching fails.
3. **Truth-first generation.** Always generate the *true* merchant/category/intent first, THEN corrupt it into the raw string. The answer key exists by construction — never guess labels after the fact.
4. **Never leak the answer key.** The engine's input and output must only ever use the INPUT columns. The `true_*` answer-key columns are for evaluation only — the engine must not read them.
5. **Deterministic-first, LLM-last.** Order is regex → exact → fuzzy → vector, and only then the LLM. The LLM never sees raw strings, only validated JSON.
6. **Pydantic guards the output.** Every enriched transaction is validated against the `EnrichedTransaction` model before it leaves the engine.
7. **Test each piece before moving on.** After generating or building anything, print samples / run a quick check. Don't chain steps blindly.

## Tech stack

Python 3.11 · pandas · rapidfuzz (fuzzy match) · chromadb (small local vector store, fallback only) · pydantic v2 · fastapi + uvicorn · google-genai (Gemini LLM — free tier) · python-dotenv (loads the API key). Prefer the standard library where possible; don't add dependencies not listed here without saying why.
