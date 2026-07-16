"""Generate data/merchants.csv (Table 1 in docs/DATA_SPEC.md).

Seed merchants (real anchors from the spec) are used verbatim, then expanded
with a curated brand long tail and a procedurally generated long tail to
reach ~500 merchants total, keeping ~70% in_directory=true.

Truth-first: every field here IS the truth (there is no corruption step for
merchants.csv itself -- descriptor_patterns are the "known aliases" Layer 1
keeps in its directory; raw transaction strings are corrupted later in
gen_transactions.py).
"""

import csv
import json
import random
import re
from pathlib import Path

RNG_SEED = 42
TARGET_TOTAL = 500
TARGET_IN_DIRECTORY_RATIO = 0.70

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = DATA_DIR / "merchants.csv"

CATEGORIES = [
    "food", "groceries", "transport", "shopping", "bills", "telecom",
    "health", "entertainment", "travel", "education", "government", "charity",
]

CITY_AR = {
    "RYD": "الرياض", "JED": "جدة", "DMM": "الدمام", "MAK": "مكة",
    "MAD": "المدينة", "KHOBAR": "الخبر", "TIF": "الطائف", "ABHA": "أبها",
    "QASSIM": "القصيم", "TABUK": "تبوك", "HAIL": "حائل", "JIZAN": "جازان",
    "NJRAN": "نجران", "YANBU": "ينبع",
}
CITIES = list(CITY_AR.keys())
NATIONAL_CITIES = ["RYD", "JED", "DMM", "MAK", "MAD", "KHOBAR"]

# ---------------------------------------------------------------------------
# Seed merchants -- used verbatim, from docs/DATA_SPEC.md "Seed merchants"
# ---------------------------------------------------------------------------
SEED_MERCHANTS = [
    ("McDonald's", "ماكدونالدز", "food", ["MCD", "MCDONALDS", "MCD*", "SP*MCD"]),
    ("Al Baik", "البيك", "food", ["ALBAIK", "AL BAIK", "BAIK", "البيك"]),
    ("Herfy", "هرفي", "food", ["HERFY", "HERFY REST"]),
    ("Kudu", "كودو", "food", ["KUDU"]),
    ("Starbucks", "ستاربكس", "food", ["STARBUCKS", "SBUX"]),
    ("Barn's", "بارنز", "food", ["BARNS", "BARN'S CAFE"]),
    ("Half Million", "نص مليون", "food", ["HALF MILLION", "HALFMILLION"]),
    ("Jahez", "جاهز", "food", ["JAHEZ", "JAHEZ*"]),
    ("HungerStation", "هنقرستيشن", "food", ["HUNGERSTATION", "HUNGER STATION", "HS*"]),
    ("Panda", "بنده", "groceries", ["PANDA", "PANDA HYPER", "بنده"]),
    ("Othaim", "العثيم", "groceries", ["OTHAIM", "AL OTHAIM"]),
    ("Danube", "الدانوب", "groceries", ["DANUBE"]),
    ("Tamimi", "التميمي", "groceries", ["TAMIMI", "TAMIMI MARKETS"]),
    ("Carrefour", "كارفور", "groceries", ["CARREFOUR", "CRF"]),
    ("Aldrees", "الدريس", "transport", ["ALDREES", "AL DREES STATION"]),
    ("Sasco", "ساسكو", "transport", ["SASCO"]),
    ("Uber", "أوبر", "transport", ["UBER", "UBER*TRIP"]),
    ("Careem", "كريم", "transport", ["CAREEM", "CAREEM*"]),
    ("STC", "إس تي سي", "telecom", ["STC", "STC PREPAID"]),
    ("Mobily", "موبايلي", "telecom", ["MOBILY"]),
    ("Zain", "زين", "telecom", ["ZAIN"]),
    ("Jarir", "جرير", "shopping", ["JARIR", "JARIR BOOKSTORE"]),
    ("Extra", "اكسترا", "shopping", ["EXTRA", "EXTRA STORES"]),
    ("Noon", "نون", "shopping", ["NOON", "NOON.COM"]),
    ("Amazon.sa", "أمازون", "shopping", ["AMZN", "AMZN MKTP", "AMAZON.SA"]),
    ("Nahdi", "النهدي", "health", ["NAHDI", "AL NAHDI PHARMACY"]),
    ("Al Dawaa", "الدواء", "health", ["AL DAWAA", "DAWAA"]),
    ("IKEA", "ايكيا", "shopping", ["IKEA"]),
    ("Netflix", "نتفلكس", "entertainment", ["NETFLIX", "NETFLIX.COM"]),
    ("Shahid", "شاهد", "entertainment", ["SHAHID", "SHAHID VIP"]),
    ("SEC (electricity)", "السعودية للكهرباء", "bills", ["SADAD-SEC", "الشركة السعودية للكهرباء"]),
    ("NWC (water)", "المياه الوطنية", "bills", ["NWC", "SADAD-NWC"]),
    ("Absher", "أبشر", "government", ["ABSHER", "MOI-ABSHER"]),
    ("Saudia", "السعودية", "travel", ["SAUDIA", "SAUDIA AIRLINES"]),
    ("flynas", "طيران ناس", "travel", ["FLYNAS"]),
]

# Manual overrides for a handful of very recognizable amounts (SAR).
SEED_AMOUNT_OVERRIDES = {
    "McDonald's": (35, 15), "Al Baik": (45, 18), "Starbucks": (28, 12),
    "Netflix": (45, 8), "Shahid": (40, 6), "STC": (150, 60),
    "SEC (electricity)": (350, 150), "NWC (water)": (110, 40),
    "Saudia": (1200, 500), "flynas": (450, 200), "Absher": (60, 40),
}
# Real anchors are mostly known to Layer 1; a few stay unknown on purpose.
SEED_NOT_IN_DIRECTORY = {"Half Million", "Barn's"}

# ---------------------------------------------------------------------------
# Curated brand long tail (real/plausible Saudi brands, not in the seed list)
# ---------------------------------------------------------------------------
CURATED_TAIL = {
    "food": [
        ("Domino's Pizza", "دومينوز بيتزا"), ("Pizza Hut", "بيتزا هت"),
        ("KFC", "كنتاكي"), ("Burger King", "برجر كنج"), ("Hardee's", "هارديز"),
        ("Subway", "صب واي"), ("Little Caesars", "ليتل سيزر"),
        ("Fuddruckers", "فودراكرز"), ("Shake Shack", "شيك شاك"),
        ("Wingstop", "وينج ستوب"), ("Papa John's", "بابا جونز"),
        ("Texas Chicken", "تكساس تشكن"), ("Tim Hortons", "تيم هورتنز"),
        ("Costa Coffee", "كوستا كوفي"), ("Caribou Coffee", "كاريبو كوفي"),
        ("Dr. Cafe", "دكتور كافيه"), ("Al Romansiah", "الرومانسية"),
        ("Mama Noura", "ماما نورة"), ("Al Tazaj", "التازج"),
        ("Molano", "مولانو"), ("Salloum Restaurant", "مطعم سلوم"),
    ],
    "groceries": [
        ("Bin Dawood", "بن داود"), ("Lulu Hypermarket", "لولو هايبرماركت"),
        ("Manuel Market", "مانويل ماركت"), ("Farm Superstores", "فارم سوبر ستورز"),
        ("Sary", "ساري"), ("Nana Direct", "نعناع"),
        ("Al Jazira Supermarket", "سوبرماركت الجزيرة"),
    ],
    "transport": [
        ("Jeeny", "جيني"), ("Mrsool", "مرسول"), ("Petromin", "بترومين"),
        ("Enjaz Station", "محطة إنجاز"),
    ],
    "telecom": [
        ("Virgin Mobile KSA", "فيرجن موبايل"), ("Lebara", "ليبارا"),
        ("Salam", "سلام"), ("Etihad Atheeb", "اتحاد عذيب"),
    ],
    "shopping": [
        ("Centrepoint", "سنتربوينت"), ("Home Centre", "هوم سنتر"),
        ("Adidas", "اديداس"), ("Nike", "نايك"), ("H&M", "اتش اند ام"),
        ("Zara", "زارا"), ("Shein", "شي إن"), ("Namshi", "نمشي"),
        ("SACO", "ساكو"), ("Virgin Megastore", "فيرجن ميجاستور"),
        ("Al Hokair Fashion Group", "الحكير للأزياء"),
    ],
    "health": [
        ("Whites Pharmacy", "صيدلية وايتس"), ("United Pharmacy", "الصيدلية المتحدة"),
        ("Dr. Sulaiman Al Habib Hospital", "مستشفى د. سليمان الحبيب"),
        ("Saudi German Hospital", "المستشفى السعودي الألماني"),
        ("Mouwasat Hospital", "مواساة"), ("Al Hammadi Hospital", "الحمادي"),
    ],
    "entertainment": [
        ("Spotify", "سبوتيفاي"), ("Anghami", "أنغامي"), ("OSN", "او اس ان"),
        ("STC TV", "إس تي سي تي في"), ("PlayStation Store", "بلايستيشن ستور"),
        ("Vox Cinemas", "فوكس سينما"), ("Muvi Cinemas", "موفي سينما"),
        ("Boulevard Riyadh City", "بوليفارد رياض سيتي"),
    ],
    "bills": [
        ("Cool District Cooling", "كول للتبريد المركزي"), ("Marafiq", "مرافق"),
    ],
    "travel": [
        ("flyadeal", "طيران أديل"), ("Almosafer", "المسافر"),
        ("Booking.com", "بوكينج"), ("Trip.com", "تريب دوت كوم"),
        ("Rehlati", "رحلتي"), ("Seera Group", "مجموعة سيرا"),
    ],
    "education": [
        ("Noon Academy", "نون أكاديمي"), ("Rwaq", "رواق"), ("Udemy", "يوديمي"),
        ("Coursera", "كورسيرا"), ("Al Faisal University", "جامعة الفيصل"),
        ("Al Nahda Schools", "مدارس النهضة"),
    ],
    "government": [
        ("Tawakkalna", "توكلنا"), ("Muqeem", "مقيم"), ("Najiz", "ناجز"),
        ("Sadad Traffic Fines", "ساداد مخالفات مرورية"), ("Baladi", "بلدي"),
    ],
    "charity": [
        ("Ehsan", "إحسان"), ("Sanid", "سند"),
        ("Saudi Red Crescent", "الهلال الأحمر السعودي"),
    ],
}

# Subscription-style brands recur monthly regardless of category rule below.
MONTHLY_SUBSCRIPTIONS = {
    "Netflix", "Shahid", "Spotify", "Anghami", "OSN", "STC TV",
    "PlayStation Store", "Noon Academy", "Rwaq", "Udemy", "Coursera",
}
AGGREGATOR_APPS = ["JAHEZ", "HUNGERSTATION", "TOYOU", "MRSOOL"]
AGGREGATOR_HOST_BRANDS = {"Jahez", "HungerStation"}

# ---------------------------------------------------------------------------
# Procedural long tail (generic small/local merchants to fill out the ~500)
# ---------------------------------------------------------------------------
# (english noun, matching arabic noun) pairs -- keep them semantically paired
# so a procedurally generated name doesn't get a mismatched EN/AR translation.
PROCEDURAL_NOUNS = {
    "food": [
        ("Restaurant", "مطعم"), ("Cafe", "مقهى"), ("Grill", "مشوي"),
        ("Kitchen", "مطبخ"), ("Bakery", "مخبز"), ("Diner", "مطعم شعبي"),
        ("Eatery", "مطعم صغير"), ("Bistro", "بيسترو"),
    ],
    "groceries": [
        ("Grocery", "بقالة"), ("Mart", "تموينات"),
        ("Supermarket", "سوبر ماركت"), ("Store", "محل بقالة"),
    ],
    "transport": [
        ("Fuel Station", "محطة وقود"), ("Gas Station", "محطة بنزين"),
        ("Taxi Service", "تاكسي"), ("Parking", "موقف سيارات"),
    ],
    "shopping": [
        ("Boutique", "بوتيك"), ("Store", "متجر"), ("Shop", "محل"),
        ("Outlet", "آوتلت"), ("Mall", "مول"),
    ],
    "bills": [("Utility Co", "مرافق"), ("Services", "خدمات")],
    "telecom": [("Telecom", "اتصالات"), ("Mobile Shop", "محل جوالات")],
    "health": [
        ("Pharmacy", "صيدلية"), ("Clinic", "عيادة"),
        ("Medical Center", "مركز طبي"),
    ],
    "entertainment": [
        ("Cinema", "سينما"), ("Game Zone", "صالة ألعاب"), ("Club", "نادي"),
    ],
    "travel": [("Travel Agency", "وكالة سفريات"), ("Tours", "رحلات")],
    "education": [
        ("Institute", "معهد"), ("Academy", "أكاديمية"),
        ("Training Center", "مركز تدريب"),
    ],
    "government": [
        ("Government Office", "مكتب حكومي"), ("Service Center", "مركز خدمة"),
    ],
    "charity": [("Charity", "جمعية خيرية"), ("Foundation", "مؤسسة")],
}

# Roughly matches the real-world density of each category in daily spend.
PROCEDURAL_WEIGHTS = {
    "food": 0.20, "groceries": 0.12, "transport": 0.08, "shopping": 0.18,
    "bills": 0.04, "telecom": 0.03, "health": 0.10, "entertainment": 0.08,
    "travel": 0.06, "education": 0.05, "government": 0.03, "charity": 0.03,
}

AMOUNT_RANGES = {
    # category: (low_mean, high_mean, std_ratio)
    "food": (15, 90, 0.40), "groceries": (60, 350, 0.50),
    "transport": (40, 220, 0.45), "shopping": (60, 700, 0.60),
    "bills": (60, 400, 0.35), "telecom": (50, 250, 0.30),
    "health": (30, 450, 0.50), "entertainment": (25, 90, 0.30),
    "travel": (300, 2800, 0.50), "education": (150, 2500, 0.50),
    "government": (20, 450, 0.60), "charity": (20, 400, 0.60),
}


def pick_amount(category, rng):
    low, high, std_ratio = AMOUNT_RANGES[category]
    mean = round(rng.uniform(low, high), 2)
    std = round(mean * std_ratio, 2)
    return mean, std


def pick_recurrence(category, name_en):
    if category in ("bills", "telecom"):
        return "monthly"
    if name_en in MONTHLY_SUBSCRIPTIONS:
        return "monthly"
    return "none"


def pick_aggregator(category, name_en, rng):
    if name_en in AGGREGATOR_HOST_BRANDS:
        return ""
    if category == "food" and rng.random() < 0.25:
        return rng.choice(AGGREGATOR_APPS)
    return ""


def pick_cities(in_directory, rng):
    if in_directory and rng.random() < 0.6:
        return sorted(rng.sample(NATIONAL_CITIES, k=rng.randint(3, len(NATIONAL_CITIES))))
    return sorted(rng.sample(CITIES, k=rng.randint(1, 3)))


def gen_descriptor_patterns(name_en, rng):
    upper = name_en.upper().replace("'", "")
    patterns = {upper}
    compact = re.sub(r"[^A-Z0-9]", "", upper)
    if compact and compact != upper:
        patterns.add(compact)
    if " " in upper:
        patterns.add(upper.replace(" ", "_"))
    words = upper.split()
    if len(words) > 1:
        abbrev = "".join(w[0] for w in words if w[0].isalnum())
        if len(abbrev) >= 2:
            patterns.add(abbrev)
    if rng.random() < 0.3 and compact:
        patterns.add("SP*" + compact[:8])
    return sorted(patterns)[:5]


def build_seed_rows(rng):
    rows = []
    for name_en, name_ar, category, patterns in SEED_MERCHANTS:
        in_directory = name_en not in SEED_NOT_IN_DIRECTORY
        mean, std = SEED_AMOUNT_OVERRIDES.get(name_en) or pick_amount(category, rng)
        rows.append({
            "name_en": name_en, "name_ar": name_ar, "category": category,
            "in_directory": in_directory,
            "descriptor_patterns": list(patterns),
            "amount_mean": mean, "amount_std": std,
            "recurrence": pick_recurrence(category, name_en),
            "aggregator": pick_aggregator(category, name_en, rng),
            "cities": pick_cities(in_directory, rng),
        })
    return rows


def build_curated_rows(rng):
    rows = []
    for category, brands in CURATED_TAIL.items():
        for name_en, name_ar in brands:
            in_directory = rng.random() < 0.80
            mean, std = pick_amount(category, rng)
            rows.append({
                "name_en": name_en, "name_ar": name_ar, "category": category,
                "in_directory": in_directory,
                "descriptor_patterns": gen_descriptor_patterns(name_en, rng),
                "amount_mean": mean, "amount_std": std,
                "recurrence": pick_recurrence(category, name_en),
                "aggregator": pick_aggregator(category, name_en, rng),
                "cities": pick_cities(in_directory, rng),
            })
    return rows


def build_procedural_rows(rng, count, used_names):
    total_weight = sum(PROCEDURAL_WEIGHTS.values())
    counts = {cat: round(count * w / total_weight) for cat, w in PROCEDURAL_WEIGHTS.items()}
    # Fix rounding drift so the sum matches `count` exactly.
    drift = count - sum(counts.values())
    cats_cycle = list(counts.keys())
    i = 0
    while drift != 0:
        cat = cats_cycle[i % len(cats_cycle)]
        counts[cat] += 1 if drift > 0 else -1
        drift += -1 if drift > 0 else 1
        i += 1

    rows = []
    for category, n in counts.items():
        noun_pairs = PROCEDURAL_NOUNS[category]
        made = 0
        attempts = 0
        while made < n and attempts < n * 50:
            attempts += 1
            city = rng.choice(CITIES)
            noun_en, noun_ar = rng.choice(noun_pairs)
            name_en = f"{city.title()} {noun_en}"
            name_ar = f"{noun_ar} {CITY_AR[city]}"
            if name_en in used_names:
                name_en = f"{name_en} {rng.randint(2, 99)}"
            used_names.add(name_en)
            in_directory = rng.random() < 0.55
            mean, std = pick_amount(category, rng)
            rows.append({
                "name_en": name_en, "name_ar": name_ar, "category": category,
                "in_directory": in_directory,
                "descriptor_patterns": gen_descriptor_patterns(name_en, rng),
                "amount_mean": mean, "amount_std": std,
                "recurrence": pick_recurrence(category, name_en),
                "aggregator": pick_aggregator(category, name_en, rng),
                "cities": pick_cities(in_directory, rng),
            })
            made += 1
    return rows


def balance_in_directory_ratio(rows, rng, target_ratio):
    total = len(rows)
    target_true = round(total * target_ratio)
    current_true = sum(1 for r in rows if r["in_directory"])
    idx = list(range(total))
    rng.shuffle(idx)
    if current_true > target_true:
        to_flip = current_true - target_true
        for i in idx:
            if to_flip == 0:
                break
            if rows[i]["in_directory"]:
                rows[i]["in_directory"] = False
                rows[i]["cities"] = pick_cities(False, rng)
                to_flip -= 1
    elif current_true < target_true:
        to_flip = target_true - current_true
        for i in idx:
            if to_flip == 0:
                break
            if not rows[i]["in_directory"]:
                rows[i]["in_directory"] = True
                rows[i]["cities"] = pick_cities(True, rng)
                to_flip -= 1


def main():
    rng = random.Random(RNG_SEED)

    seed_rows = build_seed_rows(rng)
    curated_rows = build_curated_rows(rng)
    used_names = {r["name_en"] for r in seed_rows + curated_rows}

    remaining = TARGET_TOTAL - len(seed_rows) - len(curated_rows)
    procedural_rows = build_procedural_rows(rng, remaining, used_names)

    all_rows = seed_rows + curated_rows + procedural_rows
    balance_in_directory_ratio(all_rows, rng, TARGET_IN_DIRECTORY_RATIO)
    rng.shuffle(all_rows)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "merchant_id", "name_en", "name_ar", "category", "in_directory",
        "descriptor_patterns", "amount_mean", "amount_std", "recurrence",
        "aggregator", "cities",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, row in enumerate(all_rows, start=1):
            writer.writerow({
                "merchant_id": f"M{i:04d}",
                "name_en": row["name_en"],
                "name_ar": row["name_ar"],
                "category": row["category"],
                "in_directory": row["in_directory"],
                "descriptor_patterns": json.dumps(row["descriptor_patterns"], ensure_ascii=False),
                "amount_mean": row["amount_mean"],
                "amount_std": row["amount_std"],
                "recurrence": row["recurrence"],
                "aggregator": row["aggregator"],
                "cities": json.dumps(row["cities"], ensure_ascii=False),
            })

    # Rule 7: test before moving on -- print a quick self-check.
    total = len(all_rows)
    true_count = sum(1 for r in all_rows if r["in_directory"])
    cat_counts = {c: sum(1 for r in all_rows if r["category"] == c) for c in CATEGORIES}
    print(f"Wrote {total} merchants to {OUT_PATH}")
    print(f"in_directory=true ratio: {true_count}/{total} = {true_count/total:.1%}")
    print("Category spread:")
    for c in CATEGORIES:
        print(f"  {c:14s} {cat_counts[c]:4d}")


if __name__ == "__main__":
    main()
