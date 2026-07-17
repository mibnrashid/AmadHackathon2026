"""FastAPI app -- thin wrapper over engine/*.py. See docs/ENGINE_SPEC.md "API"."""

import csv
import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine.aggregate import build_dashboard
from engine.explain import chat as explain_chat, report as explain_report
from engine.predict import RecipientStats, apply_correction, enrich

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
METRICS_PATH = Path(__file__).resolve().parent.parent / "eval" / "metrics.json"


class RawTxn(BaseModel):
    txn_id: str
    user_id: str
    raw_description: str
    amount: float
    currency: str = "SAR"
    timestamp: str
    channel: str
    counterparty_ref: str = ""


class EnrichRequest(BaseModel):
    transactions: List[RawTxn]


class CorrectRequest(BaseModel):
    txn_id: str
    category: str
    display_name: str


class ReportRequest(BaseModel):
    user_id: str
    month: str


class ChatRequest(BaseModel):
    user_id: str
    message: str
    month: Optional[str] = None


def _load_txn_store():
    with open(DATA_DIR / "transactions.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    raw_txns = [{
        "txn_id": r["txn_id"], "user_id": r["user_id"], "raw_description": r["raw_description"],
        "amount": float(r["amount"]), "currency": r["currency"], "timestamp": r["timestamp"],
        "channel": r["channel"], "counterparty_ref": r["counterparty_ref"],
    } for r in rows]
    return {t["txn_id"]: t for t in raw_txns}, RecipientStats.from_raw_txns(raw_txns)


TXN_STORE, RECIPIENT_STATS = _load_txn_store()

app = FastAPI(title="Khawarizm engine API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/enrich")
def enrich_endpoint(req: EnrichRequest):
    return {"transactions": [enrich(t.model_dump(), recipient_stats=RECIPIENT_STATS) for t in req.transactions]}


@app.post("/correct")
def correct_endpoint(req: CorrectRequest):
    txn = TXN_STORE.get(req.txn_id)
    if not txn:
        raise HTTPException(404, f"unknown txn_id {req.txn_id}")
    apply_correction(txn["user_id"], txn["raw_description"], txn["channel"], txn["counterparty_ref"],
                      req.category, req.display_name)
    return enrich(txn, recipient_stats=RECIPIENT_STATS)


@app.post("/report")
def report_endpoint(req: ReportRequest):
    return {"report_markdown": explain_report(req.user_id, req.month)}


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    return {"answer": explain_chat(req.user_id, req.message, req.month)}


@app.get("/user/{user_id}/dashboard")
def dashboard_endpoint(user_id: str, month: Optional[str] = None):
    try:
        dash = build_dashboard(user_id, month)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {
        "user": dash["user"],
        "month": dash["month"],
        "totals": dash["totals"],
        "by_category": dash["by_category"],
        "top_merchants": dash["top_merchants"],
        "transactions": [t.model_dump(mode="json") for t in dash["transactions"]],
    }


@app.get("/metrics")
def metrics_endpoint():
    if not METRICS_PATH.exists():
        raise HTTPException(404, "metrics.json not found -- run eval/run_eval.py first")
    return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
