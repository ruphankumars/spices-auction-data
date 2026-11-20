"""Form D (Advance Auction Report) extractor - the statutory summary page."""
import re
from .numbers import numbers_in

FIELDS = [  # (key, keyword regex, decimals)
    ("fresh_arrivals_kg", r"fresh\s*arriv", 3),
    ("put_for_auction_kg", r"total\s*quantity\s*put|qty\.?\s*put", 3),
    ("sold_kg", r"(total\s*)?quantity\s*sold|qty\.?\s*sold|total.{0,12}sold", 3),
    ("withdrawn_kg", r"withdrawn", 3),
    ("returned_kg", r"returned", 3),
    ("value_rs", r"value\s*of\s*(the\s*)?sale", 2),
    ("max_price", r"maximum", 2),
    ("min_price", r"minimum", 2),
    ("avg_price", r"average", 2),
]


def is_formd(text):
    return bool(re.search(r"form\s*[-–]?\s*d\b", text[:400], re.I) and re.search(r"advance\s*auction", text, re.I))


def _head(text, key, pat):
    m = re.search(pat, text, re.I)
    return m.group(1).strip() if m else None


def parse(text):
    lines = [l for l in text.splitlines() if l.strip()]
    rec = {}
    rec["season"] = _head(text, "season", r"season\s*[:>]?\s*(20\d\d\s*-\s*20\d\d)")
    m = re.search(r"auction\s*(?:no|number)\.?\s*[:>]?\s*(\d{1,3})\b", text, re.I)
    rec["auction_no"] = int(m.group(1)) if m else None
    rec["date"] = None
    for m in re.finditer(r"(?<![\d/])(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)", text):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= d <= 31 and 1 <= mo <= 12:
            rec["date"] = f"{y}-{mo:02d}-{d:02d}"
            break
    rec["licence"] = _head(text, "lic", r"(EAUC/CS/[\w/-]+)")
    used = set()
    for key, pat, dec in FIELDS:
        for i, l in enumerate(lines):
            if i in used or not re.search(pat, l, re.I):
                continue
            nums = numbers_in(re.sub(r"^\W*\(?\w{1,2}\)|^\s*\d{1,2}\.", "", l), dec)
            nums = [n for n in nums if n not in (5, 6, 7, 8, 9, 10)]  # 'S.No. 5 and 6' refs
            if not nums and re.search(r"\bnil\b", l, re.I):
                nums = [0.0]
            if not nums and i + 1 < len(lines):  # value wrapped to next line
                nums = numbers_in(lines[i + 1], dec)
            if not nums:
                continue
            used.add(i)
            if key in ("max_price", "min_price"):
                # '3,494.00 / kgs. 100.200' pairs -> keep prices (>=500)
                nums = [n for n in nums if n >= 500] or nums
            rec[key] = nums[0]
            if len(nums) > 1 and key in ("max_price", "min_price"):
                rec[key + "_kl"], rec[key + "_tn"] = nums[0], nums[1]
                rec[key] = max(nums[:2]) if key == "max_price" else min(nums[:2])
            elif len(nums) > 1:  # two-column Kerala / Tamil Nadu layout
                rec[key + "_kl"], rec[key + "_tn"] = nums[0], nums[1]
                rec[key] = nums[0] if key == "avg_price" else nums[0] + nums[1]
            break
    if "avg_price_tn" in rec and rec.get("sold_kg"):
        rec["avg_price"] = round(rec["value_rs"] / rec["sold_kg"], 2) if rec.get("value_rs") else rec["avg_price"]
    rec["top_buyers"] = top_buyers(lines)
    rec["checks"] = checks(rec)
    return rec


def top_buyers(lines):
    out, on = [], False
    for l in lines:
        if re.search(r"highest\s*(buyer|bidder)", l, re.I):
            on = True
            continue
        if not on:
            continue
        if re.search(r"^\s*total\b|place\s*[:of]|signature|date\s*:", l, re.I):
            break
        nums = numbers_in(re.sub(r"C\.?S\.?/[\w/.-]+|\b\d{1,2}\s+(?=[A-Z])", " ", l))
        names = re.sub(r"[\d,.|/'‘:;©%\-]+", " ", re.sub(r"C\.?S\.?/[\w/.-]+", " ", l))
        name = re.sub(r"\s+", " ", names).strip(" .")
        if len(nums) >= 2 and len(name) >= 3:
            out.append({"buyer": name, "kg": nums[-2], "value_rs": nums[-1]})
    return out[:5]


def checks(r):
    c = {}
    if all(k in r for k in ("put_for_auction_kg", "sold_kg")):
        exp = r["put_for_auction_kg"] - r.get("withdrawn_kg", 0)
        c["sold_eq_put_minus_withdrawn"] = abs(exp - r["sold_kg"]) < 1
    if all(k in r for k in ("value_rs", "sold_kg", "avg_price")) and r["sold_kg"]:
        c["avg_price_consistent"] = abs(r["value_rs"] / r["sold_kg"] - r["avg_price"]) / r["avg_price"] < 0.02
    if all(k in r for k in ("max_price", "min_price", "avg_price")):
        c["min_le_avg_le_max"] = r["min_price"] <= r["avg_price"] <= r["max_price"]
    for b in r.get("top_buyers", []):
        if b["kg"]:
            c.setdefault("top_buyer_rates_plausible", True)
            if not 1500 < b["value_rs"] / b["kg"] < 6000:
                c["top_buyer_rates_plausible"] = False
    return c
