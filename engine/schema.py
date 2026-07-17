"""Output contract -- EnrichedTransaction (Pydantic v2). Match ENGINE_SPEC.md exactly.

This is the contract with the frontend; engine/predict.py builds these.
"""

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class Merchant(BaseModel):
    name: str
    slug: str


class Counterparty(BaseModel):
    label: str
    kind: Literal["person", "business", "wallet", "self"]


class EnrichedTransaction(BaseModel):
    txn_id: str
    raw_description: str
    type: Literal["purchase", "transfer", "income", "cash"]
    display_name: str
    category: str
    merchant: Optional[Merchant] = None
    counterparty: Optional[Counterparty] = None
    amount: float
    currency: str
    timestamp: datetime
    confidence: float
    resolved_by: Literal["exact", "fuzzy", "vector", "rules", "correction"]
    is_ambiguous: bool
