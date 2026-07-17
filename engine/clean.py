"""Layer 1 -- Clean: exact -> fuzzy (rapidfuzz) -> vector (chromadb) merchant resolution.

Reads only merchants.csv, and only rows where in_directory=True -- that's
Layer 1's directory. Merchants with in_directory=False are unknown to Layer 1
by construction, so they legitimately fail to resolve here and require the
vector fallback (or fail gracefully) -- that's the point of that dataset flag.
No answer-key columns exist in merchants.csv, so there is nothing to leak
(CLAUDE.md rule 4).
"""

import csv
import json
from functools import lru_cache
from pathlib import Path

import chromadb
from rapidfuzz import fuzz, process

from engine.normalize import normalize

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MERCHANTS_PATH = DATA_DIR / "merchants.csv"

EXACT_CONFIDENCE = 0.97
FUZZY_THRESHOLD = 85
VECTOR_MAX_DISTANCE = 0.60  # chromadb cosine distance; below this counts as a hit

# Channels that never carry a merchant -- Layer 2 handles these via context rules.
NO_MERCHANT_CHANNELS = {"atm", "transfer", "wallet"}


class MerchantCatalog:
    def __init__(self):
        self.merchants = self._load_known_merchants()
        self.exact_index = {}
        self.fuzzy_aliases = []  # (normalized_alias, merchant_id)
        self._build_exact_and_fuzzy()
        self._client = chromadb.Client()
        self._collection = self._build_vector_store()

    def _load_known_merchants(self):
        with open(MERCHANTS_PATH, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        merchants = {}
        for r in rows:
            if r["in_directory"] != "True":
                continue
            merchants[r["merchant_id"]] = {
                "merchant_id": r["merchant_id"],
                "name_en": r["name_en"],
                "name_ar": r["name_ar"],
                "category": r["category"],
                "descriptor_patterns": json.loads(r["descriptor_patterns"]),
            }
        return merchants

    def _build_exact_and_fuzzy(self):
        for mid, m in self.merchants.items():
            aliases = {m["name_en"], m["name_ar"], *m["descriptor_patterns"]}
            for alias in aliases:
                norm = normalize(alias)
                if not norm:
                    continue
                self.exact_index.setdefault(norm, mid)
                self.fuzzy_aliases.append((norm, mid))

    def _build_vector_store(self):
        collection = self._client.get_or_create_collection("merchants")
        ids, docs, metadatas = [], [], []
        for mid, m in self.merchants.items():
            text = f"{m['name_en']} {m['name_ar']} {' '.join(m['descriptor_patterns'])}"
            ids.append(mid)
            docs.append(normalize(text))
            metadatas.append({"merchant_id": mid})
        if ids:
            collection.add(ids=ids, documents=docs, metadatas=metadatas)
        return collection

    def lookup_exact(self, norm):
        mid = self.exact_index.get(norm)
        return self.merchants[mid] if mid else None

    def lookup_fuzzy(self, norm):
        if not norm or not self.fuzzy_aliases:
            return None, 0
        choices = [alias for alias, _ in self.fuzzy_aliases]
        match = process.extractOne(norm, choices, scorer=fuzz.token_set_ratio)
        if not match:
            return None, 0
        _, score, idx = match
        mid = self.fuzzy_aliases[idx][1]
        return (self.merchants[mid], score) if score >= FUZZY_THRESHOLD else (None, score)

    def lookup_vector(self, norm):
        if not norm:
            return None, 1.0
        result = self._collection.query(query_texts=[norm], n_results=1)
        ids = result.get("ids") or [[]]
        if not ids[0]:
            return None, 1.0
        distance = result["distances"][0][0]
        mid = result["metadatas"][0][0]["merchant_id"]
        if distance <= VECTOR_MAX_DISTANCE:
            return self.merchants[mid], distance
        return None, distance


_catalog = None


def get_catalog():
    global _catalog
    if _catalog is None:
        _catalog = MerchantCatalog()
    return _catalog


@lru_cache(maxsize=None)
def clean(raw_description: str) -> dict:
    """Resolve a raw string to a known merchant. Pure string->merchant; the
    caller decides (via `channel`) whether it's worth calling at all.
    Cached -- many raw strings repeat verbatim across a transaction history."""
    norm = normalize(raw_description)
    catalog = get_catalog()

    merchant = catalog.lookup_exact(norm)
    if merchant:
        return {"merchant": merchant, "resolved_by": "exact", "confidence": EXACT_CONFIDENCE, "normalized": norm}

    merchant, score = catalog.lookup_fuzzy(norm)
    if merchant:
        return {"merchant": merchant, "resolved_by": "fuzzy", "confidence": round(score / 100, 3), "normalized": norm}

    merchant, distance = catalog.lookup_vector(norm)
    if merchant:
        confidence = round(max(0.0, 1 - distance), 3)
        return {"merchant": merchant, "resolved_by": "vector", "confidence": confidence, "normalized": norm}

    return {"merchant": None, "resolved_by": "vector", "confidence": 0.1, "normalized": norm}


def should_attempt_merchant_lookup(channel: str) -> bool:
    return channel not in NO_MERCHANT_CHANNELS
