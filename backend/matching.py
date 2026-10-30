import re
import os
import sys
from decimal import Decimal
from datetime import datetime
from rapidfuzz import fuzz

# Ensure local imports work regardless of execution directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import (
    get_connection,
    get_invoice_balance,
    get_payment_balance,
    to_decimal
)

# ==========================================
# CONFIGURATION
# ==========================================

MINIMUM_SCORE = 40
HIGH_CONFIDENCE = 80
MEDIUM_CONFIDENCE = 60

COMMON_SUFFIXES = [
    r"\bpvt\s+ltd\b", r"\bprivate\s+limited\b", r"\bltd\b",
    r"\blimited\b", r"\bllc\b", r"\bcorp\b", r"\bcorporation\b",
    r"\binc\b", r"\benterprises\b", r"\bent\b", r"\bsolutions\b",
    r"\bservices\b", r"\btechnologies\b", r"\btech\b", r"\bco\b",
    r"\bcompany\b", r"\bhub\b"
]


# ==========================================
# STRING & CUSTOMER NORMALIZATION
# ==========================================

def clean_string(s) -> str:
    if not s:
        return ""
    # lowercase, remove punctuation except alphanumeric and spaces
    clean = re.sub(r"[^\w\s]", " ", str(s).lower())
    return " ".join(clean.split())


def strip_company_suffixes(name: str) -> str:
    cleaned = clean_string(name)
    for pattern in COMMON_SUFFIXES:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def compare_customer(invoice_name, payment_name):
    inv_clean = clean_string(invoice_name)
    pay_clean = clean_string(payment_name)

    if not inv_clean or not pay_clean:
        return 0

    if inv_clean == pay_clean:
        return 100

    # Test full string token similarity
    token_sort = fuzz.token_sort_ratio(inv_clean, pay_clean)
    token_set = fuzz.token_set_ratio(inv_clean, pay_clean)

    # Test stripped suffixes (e.g. "Apex Technologies" vs "Apex Tech")
    inv_stripped = strip_company_suffixes(invoice_name)
    pay_stripped = strip_company_suffixes(payment_name)
    stripped_score = fuzz.token_sort_ratio(inv_stripped, pay_stripped)

    # Check for abbreviation (e.g. "Oasis HC" vs "Oasis Healthcare")
    words_inv = inv_clean.split()
    words_pay = pay_clean.split()
    abbr_score = 0
    if len(words_inv) > 1 and len(words_pay) > 1:
        abbr_inv = "".join(w[0] for w in words_inv)
        abbr_pay = "".join(w[0] for w in words_pay)
        if abbr_inv in pay_clean or abbr_pay in inv_clean:
            abbr_score = 75

    return max(token_sort, token_set, stripped_score, abbr_score)


# ==========================================
# INVOICE REFERENCE EXTRACTION
# ==========================================

def extract_reference(text: str):
    """Searches text/description for invoice reference patterns like INV-1001, INV1001, etc."""
    if not text:
        return []
    matches = re.findall(r"\b(INV[-_ ]?\d+)\b", str(text), flags=re.IGNORECASE)
    cleaned = [re.sub(r"[-_ ]", "", m).upper() for m in matches]
    return cleaned


def compare_reference(invoice_id, payment_ref, payment_desc):
    inv_norm = re.sub(r"[-_ ]", "", str(invoice_id)).upper()
    pay_ref_norm = re.sub(r"[-_ ]", "", str(payment_ref or "")).upper()

    # 1. Direct reference field match
    if pay_ref_norm and pay_ref_norm == inv_norm:
        return 45, "Explicit invoice reference matches exactly"

    # 2. Reference in payment description
    desc_refs = extract_reference(payment_desc)
    if inv_norm in desc_refs:
        return 40, f"Invoice reference '{invoice_id}' extracted from payment description"

    # 3. Fuzzy check inside description
    if inv_norm and inv_norm in re.sub(r"[-_ ]", "", str(payment_desc or "")).upper():
        return 35, f"Invoice number embedded in transaction description"

    return 0, ""


# ==========================================
# DATE COMPARISON
# ==========================================

def compare_dates(invoice_date, payment_date):
    if not invoice_date or not payment_date:
        return 0, "Transaction date unavailable"

    d1 = None
    d2 = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        if not d1:
            try:
                d1 = datetime.strptime(str(invoice_date).strip(), fmt)
            except ValueError:
                pass
        if not d2:
            try:
                d2 = datetime.strptime(str(payment_date).strip(), fmt)
            except ValueError:
                pass

    if not d1 or not d2:
        return 0, "Invalid date format"

    diff_days = (d2 - d1).days

    if diff_days < -2:
        return -5, f"Warning: Payment date predates invoice by {abs(diff_days)} days"
    elif 0 <= diff_days <= 5:
        return 12, f"Payment occurred within {diff_days} days of invoice"
    elif 6 <= diff_days <= 15:
        return 9, f"Payment occurred within {diff_days} days of invoice"
    elif 16 <= diff_days <= 30:
        return 6, f"Payment occurred within {diff_days} days of invoice"
    elif 31 <= diff_days <= 60:
        return 3, f"Payment occurred within {diff_days} days of invoice"
    else:
        return 0, f"Payment occurred {abs(diff_days)} days apart"


# ==========================================
# AMOUNT COMPARISON
# ==========================================

def compare_amounts(invoice_balance, payment_balance):
    inv_bal = to_decimal(invoice_balance)
    pay_bal = to_decimal(payment_balance)

    if inv_bal <= Decimal("0.00") or pay_bal <= Decimal("0.00"):
        return 0, "No available balance remaining"

    if inv_bal == pay_bal:
        return 28, f"Exact monetary balance match: {inv_bal}"

    # Partial payment
    if pay_bal < inv_bal:
        return 15, f"Payment ({pay_bal}) covers partial invoice balance ({inv_bal})"

    # Slight underpayment (e.g. bank fee deduction of 1-3%)
    discrepancy = pay_bal - inv_bal
    pct_diff = abs(discrepancy / inv_bal) * 100
    if pay_bal < inv_bal and pct_diff <= Decimal("3.0"):
        return 18, f"Near exact amount within {pct_diff:.1f}% (likely bank charge/fee deduction)"

    # Overpayment
    if pay_bal > inv_bal:
        return 0, f"Payment ({pay_bal}) exceeds invoice balance ({inv_bal})"

    return 0, "Amount mismatch"


# ==========================================
# INDIVIDUAL MATCH CALCULATION
# ==========================================

def calculate_match(invoice, payment):
    score = 0
    evidence = []

    # 1. Reference Match
    ref_score, ref_reason = compare_reference(
        invoice["invoice_id"],
        payment.get("invoice_ref", ""),
        payment.get("description", "")
    )
    score += ref_score
    if ref_reason:
        evidence.append(ref_reason)

    # 2. Customer Match
    cust_sim = compare_customer(invoice["customer"], payment["customer"])
    if cust_sim >= 90:
        score += 28
        evidence.append(f"Customer name strong match ({cust_sim}%)")
    elif cust_sim >= 75:
        score += 20
        evidence.append(f"Customer name good match ({cust_sim}%)")
    elif cust_sim >= 60:
        score += 12
        evidence.append(f"Customer name partial match ({cust_sim}%)")
    elif cust_sim >= 40:
        score += 5
        evidence.append(f"Customer name weak match ({cust_sim}%)")

    # 3. Amount Match
    inv_bal = get_invoice_balance(invoice)
    pay_bal = get_payment_balance(payment)
    amt_score, amt_reason = compare_amounts(inv_bal, pay_bal)
    score += amt_score
    if amt_reason:
        evidence.append(amt_reason)

    # 4. Date Proximity
    date_score, date_reason = compare_dates(
        invoice.get("invoice_date", ""),
        payment.get("payment_date", "")
    )
    score += date_score
    if date_reason:
        evidence.append(date_reason)

    # 5. Repeated Amount Safeguard
    # If amount matches but customer similarity is very low and no reference, penalize
    if amt_score >= 25 and cust_sim < 50 and ref_score == 0:
        score = min(score, 45)
        evidence.append("Caution: Repeated amount detected with dissimilar customer names and no reference")

    # Cap score
    score = max(0, min(100, score))

    if score >= HIGH_CONFIDENCE:
        confidence = "High"
    elif score >= MEDIUM_CONFIDENCE:
        confidence = "Medium"
    else:
        confidence = "Low"

    return {
        "score": score,
        "confidence": confidence,
        "evidence": evidence
    }


# ==========================================
# FETCH DATABASE RECORDS
# ==========================================

def fetch_records():
    with get_connection() as conn:
        invoices = conn.execute("SELECT * FROM invoices ORDER BY invoice_id").fetchall()
        payments = conn.execute("SELECT * FROM payments ORDER BY payment_id").fetchall()
        rejected = conn.execute("SELECT invoice_id, payment_id FROM decisions WHERE status = 'Rejected'").fetchall()

    return (
        [dict(i) for i in invoices],
        [dict(p) for p in payments],
        {(r["invoice_id"], r["payment_id"]) for r in rejected}
    )


# ==========================================
# GENERATE MATCH SUGGESTIONS & AMBIGUITY
# ==========================================

def generate_suggestions():
    invoices, payments, rejected = fetch_records()
    candidates = []

    for invoice in invoices:
        inv_bal = get_invoice_balance(invoice)
        if inv_bal <= Decimal("0.00"):
            continue

        for payment in payments:
            pay_bal = get_payment_balance(payment)
            if pay_bal <= Decimal("0.00"):
                continue

            pair = (invoice["invoice_id"], payment["payment_id"])
            if pair in rejected:
                continue

            res = calculate_match(invoice, payment)
            if res["score"] < MINIMUM_SCORE:
                continue

            candidates.append({
                "invoice_id": invoice["invoice_id"],
                "payment_id": payment["payment_id"],
                "invoice_customer": invoice["customer"],
                "payment_customer": payment["customer"],
                "invoice_amount": str(to_decimal(invoice["amount"])),
                "invoice_outstanding": str(inv_bal),
                "payment_amount": str(to_decimal(payment["amount"])),
                "payment_remaining": str(pay_bal),
                "suggested_allocation": str(min(inv_bal, pay_bal)),
                "confidence_score": res["score"],
                "confidence": res["confidence"],
                "evidence": res["evidence"],
                "status": "Review Required"
            })

    # Sort descending by confidence score
    candidates.sort(key=lambda x: x["confidence_score"], reverse=True)

    # Detect ambiguity (1 invoice matching multiple payments, or 1 payment matching multiple invoices)
    inv_counts = {}
    pay_counts = {}
    for c in candidates:
        if c["confidence_score"] >= MEDIUM_CONFIDENCE:
            inv_counts[c["invoice_id"]] = inv_counts.get(c["invoice_id"], 0) + 1
            pay_counts[c["payment_id"]] = pay_counts.get(c["payment_id"], 0) + 1

    for c in candidates:
        is_ambiguous = (
            inv_counts.get(c["invoice_id"], 0) > 1 or
            pay_counts.get(c["payment_id"], 0) > 1
        )
        if is_ambiguous:
            c["status"] = "Ambiguous - Review Required"
            c["evidence"].append("Ambiguity: Multiple candidate pairings exist for this record.")
        elif c["confidence"] == "High":
            c["status"] = "Ready to Confirm"
        else:
            c["status"] = "Review Required"

    return candidates
