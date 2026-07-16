# Khawarizm — Engine ↔ Frontend Contract (for Khalid)

This is the agreement between the AI engine (Musa) and the app (you). Build the whole UI against the shapes below using the sample data at the bottom — you don't need the real engine to start. When the engine is ready, the shapes stay the same, only the values become real.

---

## 1. What the engine does (one line)

It takes messy raw bank transaction strings and returns clean, structured, categorized transactions — plus a monthly report and a chat answer. You never see the messy internals; you only ever get the clean shape in section 2.

---

## 2. The output shape — `EnrichedTransaction`

Every transaction the engine returns looks exactly like this:

```json
{
  "txn_id": "T000123",
  "raw_description": "SP *MCD_2938_RYD",
  "type": "purchase",
  "display_name": "McDonald's",
  "category": "food",
  "merchant": { "name": "McDonald's", "slug": "mcdonalds" },
  "counterparty": null,
  "amount": -47.0,
  "currency": "SAR",
  "timestamp": "2026-05-14T20:11:00",
  "confidence": 0.97,
  "resolved_by": "exact",
  "is_ambiguous": false
}
```

Field-by-field:

| field | meaning / how you use it |
|---|---|
| `txn_id` | unique id. Use it as the React key and to send corrections back. |
| `raw_description` | the original messy string — show it on the "before" side. |
| `type` | one of `purchase` \| `transfer` \| `income` \| `cash`. **This tells you which block is filled:** `purchase` → `merchant` is set; `transfer`/`income` → `counterparty` is set; `cash` → both null. |
| `display_name` | the clean title to show big (e.g. "McDonald's", "Gift", "Salary"). This is the "after" side. |
| `category` | one of the 15 keys in section 3. This is the bucket you group budgets by, and the field the user can correct. |
| `merchant` | `{name, slug}` or `null`. Use `slug` to pick the logo (e.g. `mcdonalds.png`). |
| `counterparty` | `{label, kind}` or `null`. `kind` = `person` \| `business` \| `wallet` \| `self`. For transfers/income. |
| `amount` | signed number: **negative = money out, positive = money in.** |
| `currency` | usually `"SAR"`. |
| `timestamp` | ISO datetime. |
| `confidence` | 0–1. If low (< 0.6), grey the row or show a small "?" so the user can check it. |
| `resolved_by` | `exact` \| `fuzzy` \| `vector` \| `rules` \| `correction`. Optional to show — nice as a tiny "how we knew" badge. |
| `is_ambiguous` | if `true`, show the "is this right?" / tap-to-correct affordance. This is the STC Pay case. |

---

## 3. Category keys → Arabic labels

Use the English key in code; show the Arabic label.

`food` طعام ومطاعم · `groceries` بقالة وتموين · `transport` نقل ووقود · `shopping` تسوّق · `bills` فواتير ومرافق · `telecom` اتصالات وإنترنت · `health` صحة وصيدليات · `entertainment` ترفيه واشتراكات · `travel` سفر وطيران · `education` تعليم · `government` خدمات حكومية ورسوم · `charity` صدقات وتبرعات · `transfer` تحويلات · `income` دخل ورواتب · `cash` سحب نقدي

---

## 4. Endpoints

Each is a POST that returns JSON. Base URL is local for the prototype (e.g. `http://localhost:8000`).

### `POST /enrich` — clean a batch (powers the before/after screen)
You send raw transactions, you get back `EnrichedTransaction[]`.

Request:
```json
{ "transactions": [
  { "txn_id": "T000123", "raw_description": "SP *MCD_2938_RYD",
    "amount": -47.0, "currency": "SAR",
    "timestamp": "2026-05-14T20:11:00", "user_id": "U007", "channel": "pos" }
]}
```
Response: `{ "transactions": [ EnrichedTransaction, ... ] }`

`channel` is one of `pos` \| `ecom` \| `atm` \| `transfer` \| `wallet` \| `sadad`.

### `POST /correct` — user fixes a transaction (powers the STC Pay moment)
Request:
```json
{ "txn_id": "T000999", "category": "transfer", "display_name": "Gift" }
```
Response: the updated `EnrichedTransaction` (with `resolved_by: "correction"`). The engine remembers this for next time.

### `POST /report` — monthly report (LLM)
Request: `{ "user_id": "U007", "month": "2026-05" }`
Response: `{ "report_markdown": "..." }` (Arabic text).

### `POST /chat` — budget copilot (LLM)
Request: `{ "user_id": "U007", "message": "كم صرفت على المطاعم؟" }`
Response: `{ "answer": "..." }` (Arabic text).

### `GET /metrics` — live counter for the demo
Response:
```json
{ "deterministic_pct": 94, "cost_multiplier": 8, "latency_ms": 5, "accuracy_pct": 96 }
```

---

## 5. Things the frontend must handle

- **RTL + Arabic.** Set `dir="rtl"` on Arabic text. Make sure the page is UTF-8 (`<meta charset="utf-8">`) so Arabic and merchant logos render.
- **Logos by slug.** Keep a `/logos/{slug}.png` folder. If a slug has no logo, fall back to the first letter in a coloured circle.
- **Amount colour + sign.** Negative = spend (red), positive = income (green).
- **Ambiguous rows.** When `is_ambiguous` is true, show a tap target that opens a category picker and calls `/correct`.
- **Empty states.** `merchant` and `counterparty` can be null depending on `type` — never assume both exist.

---

## 6. Sample data to build against (`enriched.json`)

```json
[
  { "txn_id": "T001", "raw_description": "SP *MCD_2938_RYD", "type": "purchase",
    "display_name": "McDonald's", "category": "food",
    "merchant": { "name": "McDonald's", "slug": "mcdonalds" }, "counterparty": null,
    "amount": -47.0, "currency": "SAR", "timestamp": "2026-05-14T20:11:00",
    "confidence": 0.97, "resolved_by": "exact", "is_ambiguous": false },

  { "txn_id": "T002", "raw_description": "شراء نقاط بيع - بنده جدة", "type": "purchase",
    "display_name": "بنده", "category": "groceries",
    "merchant": { "name": "Panda", "slug": "panda" }, "counterparty": null,
    "amount": -312.5, "currency": "SAR", "timestamp": "2026-05-15T18:40:00",
    "confidence": 0.91, "resolved_by": "fuzzy", "is_ambiguous": false },

  { "txn_id": "T003", "raw_description": "ALDREES-STATION 44 RUH", "type": "purchase",
    "display_name": "Aldrees", "category": "transport",
    "merchant": { "name": "Aldrees", "slug": "aldrees" }, "counterparty": null,
    "amount": -90.0, "currency": "SAR", "timestamp": "2026-05-16T08:05:00",
    "confidence": 0.88, "resolved_by": "fuzzy", "is_ambiguous": false },

  { "txn_id": "T004", "raw_description": "STC PAY TRANSFER 0553******12", "type": "transfer",
    "display_name": "Food order (guess)", "category": "food",
    "merchant": null, "counterparty": { "label": "Friend", "kind": "person" },
    "amount": -120.0, "currency": "SAR", "timestamp": "2026-05-18T21:30:00",
    "confidence": 0.42, "resolved_by": "rules", "is_ambiguous": true },

  { "txn_id": "T005", "raw_description": "SALARY INMA-CORP MAY", "type": "income",
    "display_name": "Salary", "category": "income",
    "merchant": null, "counterparty": { "label": "Employer", "kind": "business" },
    "amount": 9000.0, "currency": "SAR", "timestamp": "2026-05-27T00:00:00",
    "confidence": 0.99, "resolved_by": "rules", "is_ambiguous": false },

  { "txn_id": "T006", "raw_description": "ATM WDL RYD 400", "type": "cash",
    "display_name": "Cash withdrawal", "category": "cash",
    "merchant": null, "counterparty": null,
    "amount": -400.0, "currency": "SAR", "timestamp": "2026-05-19T13:22:00",
    "confidence": 0.99, "resolved_by": "exact", "is_ambiguous": false }
]
```

Row **T004** is the demo hero: `is_ambiguous: true`, guessed `food`. After the user corrects it, it becomes `category: "transfer"`, `display_name: "Gift"`, `resolved_by: "correction"`.
