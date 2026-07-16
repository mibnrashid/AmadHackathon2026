# DATA_SPEC — synthetic dataset

Goal: ~500 merchants, ~150 users, ~30,000 transactions, plus a ~200-row hand-verified golden set. Three CSVs joined by id. Generate truth-first, then corrupt (see CLAUDE.md rule 3).

---

## Categories (15 — use the English key in code)

`food` طعام ومطاعم · `groceries` بقالة وتموين · `transport` نقل ووقود · `shopping` تسوّق · `bills` فواتير ومرافق · `telecom` اتصالات وإنترنت · `health` صحة وصيدليات · `entertainment` ترفيه واشتراكات · `travel` سفر وطيران · `education` تعليم · `government` خدمات حكومية ورسوم · `charity` صدقات وتبرعات · `transfer` تحويلات · `income` دخل ورواتب · `cash` سحب نقدي

---

## Table 1 — `merchants.csv`

| column | notes |
|---|---|
| merchant_id | `M0001` |
| name_en | canonical English name |
| name_ar | canonical Arabic name |
| category | one of the 15 keys (spending ones only) |
| in_directory | bool — does Layer 1 "know" it. Keep ~70% true, ~30% false |
| descriptor_patterns | list of dirty raw forms, e.g. `["MCD","MCDONALDS","MCD*","M DONALDS"]` |
| amount_mean, amount_std | typical spend, SAR |
| recurrence | `none` / `weekly` / `monthly` |
| aggregator | app name if it shows wrapped (e.g. `JAHEZ`), else empty |
| cities | list, e.g. `["RYD","JED","DMM"]` |

### Seed merchants (real anchors — expand from these to ~500)

Use these exactly; then generate a plausible long tail. Keep ~70% `in_directory=true`.

| name_en | name_ar | category | descriptor_patterns |
|---|---|---|---|
| McDonald's | ماكدونالدز | food | MCD, MCDONALDS, MCD*, SP*MCD |
| Al Baik | البيك | food | ALBAIK, AL BAIK, BAIK, البيك |
| Herfy | هرفي | food | HERFY, HERFY REST |
| Kudu | كودو | food | KUDU |
| Starbucks | ستاربكس | food | STARBUCKS, SBUX |
| Barn's | بارنز | food | BARNS, BARN'S CAFE |
| Half Million | نص مليون | food | HALF MILLION, HALFMILLION |
| Jahez | جاهز | food | JAHEZ, JAHEZ* |
| HungerStation | هنقرستيشن | food | HUNGERSTATION, HUNGER STATION, HS* |
| Panda | بنده | groceries | PANDA, PANDA HYPER, بنده |
| Othaim | العثيم | groceries | OTHAIM, AL OTHAIM |
| Danube | الدانوب | groceries | DANUBE |
| Tamimi | التميمي | groceries | TAMIMI, TAMIMI MARKETS |
| Carrefour | كارفور | groceries | CARREFOUR, CRF |
| Aldrees | الدريس | transport | ALDREES, AL DREES STATION |
| Sasco | ساسكو | transport | SASCO |
| Uber | أوبر | transport | UBER, UBER*TRIP |
| Careem | كريم | transport | CAREEM, CAREEM* |
| STC | إس تي سي | telecom | STC, STC PREPAID |
| Mobily | موبايلي | telecom | MOBILY |
| Zain | زين | telecom | ZAIN |
| Jarir | جرير | shopping | JARIR, JARIR BOOKSTORE |
| Extra | اكسترا | shopping | EXTRA, EXTRA STORES |
| Noon | نون | shopping | NOON, NOON.COM |
| Amazon.sa | أمازون | shopping | AMZN, AMZN MKTP, AMAZON.SA |
| Nahdi | النهدي | health | NAHDI, AL NAHDI PHARMACY |
| Al Dawaa | الدواء | health | AL DAWAA, DAWAA |
| IKEA | ايكيا | shopping | IKEA |
| Netflix | نتفلكس | entertainment | NETFLIX, NETFLIX.COM |
| Shahid | شاهد | entertainment | SHAHID, SHAHID VIP |
| SEC (electricity) | السعودية للكهرباء | bills | SADAD-SEC, الشركة السعودية للكهرباء |
| NWC (water) | المياه الوطنية | bills | NWC, SADAD-NWC |
| Absher | أبشر | government | ABSHER, MOI-ABSHER |
| Saudia | السعودية | travel | SAUDIA, SAUDIA AIRLINES |
| flynas | طيران ناس | travel | FLYNAS |

---

## Table 2 — `users.csv` (persona ground-truth — hidden from engine)

| column | notes |
|---|---|
| user_id | `U0001` |
| persona | student / young_family / gig_worker / professional / retiree / business_owner |
| age_band | 18-24 / 25-34 / 35-44 / 45-54 / 55+ |
| income_source | family_support / salary / gig_platform / pension / business_revenue |
| income_monthly_sar | float |
| payday_day | 1–28 |
| home_city | RYD / JED / DMM / … |
| has_rent, rent_amount, rent_day | bool + floats |
| recurring_subs | list of merchant_ids |
| does_qattah, does_remittance | bool |
| history_start, history_end | 6–12 month window |

### Persona archetypes

- **student** — 18-24, family_support 1500–2500, food/telecom/entertainment heavy, frequent small qattah, usually no rent, 1–2 subs.
- **young_family** — 25-34, salary 12–18k, groceries/health/education heavy, monthly rent, SADAD bills, occasional gifts.
- **gig_worker** — 22-30, gig_platform irregular 4–9k, fuel + food heavy, few bills.
- **professional** — 30-45, salary 20–40k, dining/travel/shopping/subs, gifts around occasions, maybe remittance.
- **retiree** — 55+, pension 4–8k, health/pharmacy/bills/charity, modest amounts.
- **business_owner** — 30-55, business_revenue irregular large (counterparty kind `self`), supplier transfers, mixed spend.

---

## Table 3 — `transactions.csv`

**INPUT columns (the engine may read these):**
`txn_id, user_id, raw_description, amount, currency, timestamp, channel, counterparty_ref`
`channel` ∈ pos / ecom / atm / transfer / wallet / sadad. `amount` signed: − out, + in.

**ANSWER-KEY columns (evaluation only — NEVER read by the engine):**
`txn_type, true_merchant_id, true_merchant_name, true_category, true_intent, is_ambiguous, is_in_directory, is_recurring_instance, corruption_ops, expected_counterparty_id, mark_for_correction, is_golden`

`txn_type` ∈ purchase / transfer / income / cash. `true_intent` for transfers ∈ gift / split / personal / remittance / bill / salary / topup.

---

## Corruption operators (sample + stack; record which fired in `corruption_ops`)

Apply to the canonical name to build `raw_description`. Each fires with a probability; several can stack.

- **abbreviate** — McDonald's → MCD
- **uppercase** — panda → PANDA
- **space→symbol** — "AL BAIK" → AL_BAIK / AL-BAIK
- **prefix inject** — prepend `POS `, `SP *`, `MADA `, `APPLEPAY *`
- **id inject** — append `_2938`, `#48213`, ` 1123`
- **city code** — append ` RYD` / ` JED` / ` DMM` / ` SA`
- **truncate** — cut to a fixed width (e.g. 12 chars)
- **transliterate (Arabic merchants)** — البيك → ALBAIK / AL BAIK / BAIK
- **aggregator wrap** — restaurant ordered via app → `JAHEZ*<merchant>` (true merchant is the restaurant, not the app)

**Arabic/Latin split:** ~75% of raw strings Latin/transliterated, ~25% Arabic. Keep the *noise* (prefixes, ids, city/POS codes) Latin even in Arabic strings — that's realistic and reduces breakage.

---

## Ambiguity + transfer logic (the heart of the thesis)

Transfers have no merchant, so Layer 1 can't help — intent must come from context. Generate `true_intent` from these rules, and make the raw string identical across intents (e.g. always `STC PAY TRANSFER …`) so only context separates them:

- end-of-month (day ≥ 26) + round hundreds + recurring recipient → **bill/rent**
- weekday evening (18–23) + amount 30–200 + one-off → **food** (via wallet)
- odd amount to a recurring "friend" recipient → **split** (qattah)
- round amount (100/200/500) + occasional + note present → **gift**
- inbound + large + monthly + employer sender → **salary**
- outbound + international beneficiary → **remittance**

Flag these rows `is_ambiguous=true`. Reuse a small pool of recipients per user (stable `counterparty_ref`) so recurrence is learnable.

---

## Distributions (make it realistic, not uniform)

- Merchant frequency: power-law — top ~20 merchants ≈ 60% of purchase volume; long tail rare.
- Mix: ~75% purchase, ~15% transfer, ~5% income, ~3% cash, ~2% FX (USD subs/travel).
- Recurring: salary 1×/mo (on payday), rent 1×/mo, subs + telecom + utilities monthly.
- Unknown merchants (`in_directory=false`) appear in ~10–15% of purchase rows → exercises vector fallback.
- ~2–3% pure garbage strings that map to nothing → tests graceful failure.

---

## Golden set + correction set

- **Golden (`is_golden=true`, ~200 rows):** stratified to cover known + unknown merchants, every ambiguous type, Arabic descriptors, transfers, and edge cases. This is the accuracy you defend.
- **Correction set (`mark_for_correction=true`, ~40 rows):** ambiguous rows held out with a known correct answer, so the demo can apply corrections live and re-measure.

Fix the RNG seed. Write all CSVs `utf-8-sig`.
