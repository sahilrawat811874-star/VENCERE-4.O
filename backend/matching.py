
import sqlite3
from decimal import Decimal
from datetime import datetime

from rapidfuzz import fuzz

from database import get_connection


# ==========================================
# CONFIGURATION
# ==========================================

MINIMUM_SCORE = 45
HIGH_CONFIDENCE = 85
MEDIUM_CONFIDENCE = 65


# ==========================================
# FINANCIAL HELPERS
# ==========================================

def to_decimal(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01")
    )


def get_invoice_balance(invoice):
    return (
        to_decimal(invoice["amount"]) -
        to_decimal(invoice["paid"])
    )


def get_payment_balance(payment):
    return (
        to_decimal(payment["amount"]) -
        to_decimal(payment["allocated"])
    )


# ==========================================
# CUSTOMER NAME MATCHING
# ==========================================

def compare_customer(invoice_name, payment_name):

    invoice_name = str(invoice_name).lower().strip()
    payment_name = str(payment_name).lower().strip()

    score = fuzz.token_sort_ratio(
        invoice_name,
        payment_name
    )

    return score


# ==========================================
# DATE COMPARISON
# ==========================================

def compare_dates(invoice_date, payment_date):

    if not invoice_date or not payment_date:
        return 0, "Transaction date unavailable"

    try:

        date1 = datetime.strptime(
            invoice_date, "%Y-%m-%d"
        )

        date2 = datetime.strptime(
            payment_date, "%Y-%m-%d"
        )

        difference = abs((date2 - date1).days)

        if difference <= 7:
            return 10, "Dates are within 7 days"

        elif difference <= 30:
            return 7, "Dates are within 30 days"

        elif difference <= 60:
            return 3, "Dates are within 60 days"

        else:
            return 0, "Dates are more than 60 days apart"

    except ValueError:
        return 0, "Invalid transaction date"


# ==========================================
# AMOUNT COMPARISON
# ==========================================

def compare_amounts(invoice_balance, payment_balance):

    invoice_balance = to_decimal(invoice_balance)
    payment_balance = to_decimal(payment_balance)

    if invoice_balance <= 0 or payment_balance <= 0:
        return 0, "No available balance"

    if invoice_balance == payment_balance:
        return 20, "Exact outstanding amount match"

    if payment_balance < invoice_balance:
        return 12, "Payment may be a partial payment"

    return 0, "Payment exceeds invoice balance"


# ==========================================
# MAIN MATCHING ENGINE
# ==========================================

def calculate_match(invoice, payment):

    score = 0
    evidence = []

    # 1. Invoice reference matching

    invoice_ref = str(
        payment["invoice_ref"] or ""
    ).strip().lower()

    invoice_id = str(
        invoice["invoice_id"]
    ).strip().lower()

    if invoice_ref and invoice_ref == invoice_id:

        score += 50

        evidence.append(
            "Invoice reference matches exactly"
        )

    # 2. Customer name matching

    customer_score = compare_customer(
        invoice["customer"],
        payment["customer"]
    )

    if customer_score >= 90:

        score += 25

        evidence.append(
            f"Customer names strongly match ({customer_score}%)"
        )

    elif customer_score >= 75:

        score += 18

        evidence.append(
            f"Customer names partially match ({customer_score}%)"
        )

    elif customer_score >= 60:

        score += 10

        evidence.append(
            f"Customer names have weak similarity ({customer_score}%)"
        )

    # 3. Amount matching

    invoice_balance = get_invoice_balance(invoice)

    payment_balance = get_payment_balance(payment)

    amount_score, amount_reason = compare_amounts(
        invoice_balance,
        payment_balance
    )

    score += amount_score

    evidence.append(amount_reason)

    # 4. Date matching

    date_score, date_reason = compare_dates(
        invoice["invoice_date"],
        payment["payment_date"]
    )

    score += date_score

    if date_score > 0:
        evidence.append(date_reason)

    # 5. Final confidence

    score = min(score, 100)

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

        invoices = conn.execute("""
            SELECT * FROM invoices
            ORDER BY invoice_id
        """).fetchall()

        payments = conn.execute("""
            SELECT * FROM payments
            ORDER BY payment_id
        """).fetchall()

        rejected = conn.execute("""
            SELECT invoice_id, payment_id
            FROM decisions
            WHERE status = 'Rejected'
        """).fetchall()

    return (
        [dict(i) for i in invoices],
        [dict(p) for p in payments],
        {
            (r["invoice_id"], r["payment_id"])
            for r in rejected
        }
    )


# ==========================================
# GENERATE MATCH SUGGESTIONS
# ==========================================

def generate_suggestions():

    invoices, payments, rejected = fetch_records()

    suggestions = []

    for invoice in invoices:

        invoice_balance = get_invoice_balance(invoice)

        if invoice_balance <= 0:
            continue

        for payment in payments:

            payment_balance = get_payment_balance(payment)

            if payment_balance <= 0:
                continue

            pair = (
                invoice["invoice_id"],
                payment["payment_id"]
            )

            # Skip rejected matches

            if pair in rejected:
                continue

            result = calculate_match(
                invoice,
                payment
            )

            if result["score"] < MINIMUM_SCORE:
                continue

            suggestions.append({

                "invoice_id": invoice["invoice_id"],

                "payment_id": payment["payment_id"],

                "customer": invoice["customer"],

                "invoice_amount": str(
                    to_decimal(invoice["amount"])
                ),

                "invoice_outstanding": str(
                    invoice_balance
                ),

                "payment_amount": str(
                    to_decimal(payment["amount"])
                ),

                "payment_remaining": str(
                    payment_balance
                ),

                "confidence_score": result["score"],

                "confidence": result["confidence"],

                "evidence": result["evidence"],

                "status": "Review Required"

            })

    # Sort by highest confidence

    suggestions.sort(
        key=lambda x: x["confidence_score"],
        reverse=True
    )

    # Detect ambiguous matches

    invoice_counts = {}
    payment_counts = {}

    for item in suggestions:

        invoice_id = item["invoice_id"]
        payment_id = item["payment_id"]

        invoice_counts[invoice_id] = (
            invoice_counts.get(invoice_id, 0) + 1
        )

        payment_counts[payment_id] = (
            payment_counts.get(payment_id, 0) + 1
        )

    for item in suggestions:

        invoice_id = item["invoice_id"]
        payment_id = item["payment_id"]

        if (
            invoice_counts[invoice_id] > 1
            or payment_counts[payment_id] > 1
        ):

            item["status"] = "Ambiguous - Review Required"

        elif item["confidence"] == "Low":

            item["status"] = "Low Confidence - Review Required"

    return suggestions


# ==========================================
# GET UNMATCHED INVOICES
# ==========================================

def get_unmatched_invoices():

    invoices, _, _ = fetch_records()

    return [
        {
            "invoice_id": invoice["invoice_id"],
            "customer": invoice["customer"],
            "outstanding": str(
                get_invoice_balance(invoice)
            )
        }
        for invoice in invoices
        if get_invoice_balance(invoice) > 0
    ]


# ==========================================
# GET UNALLOCATED PAYMENTS
# ==========================================

def get_unallocated_payments():

    _, payments, _ = fetch_records()

    return [
        {
            "payment_id": payment["payment_id"],
            "customer": payment["customer"],
            "remaining": str(
                get_payment_balance(payment)
            )
        }
        for payment in payments
        if get_payment_balance(payment) > 0
    ]


# ==========================================
# TEST MATCHING ENGINE
# ==========================================

if __name__ == "__main__":

    print("\nSMART MATCHING ENGINE")

    print("==============================")

    try:

        results = generate_suggestions()

        if not results:

            print("No matching suggestions found.")

        for item in results:

            print("\nInvoice:", item["invoice_id"])

            print("Payment:", item["payment_id"])

            print(
                "Confidence:",
                str(item["confidence_score"]) + "%"
            )

            print("Level:", item["confidence"])

            print("Status:", item["status"])

            print("Evidence:")

            for reason in item["evidence"]:
                print("-", reason)

        print("\nUnmatched Invoices:")
        print(get_unmatched_invoices())

        print("\nUnallocated Payments:")
        print(get_unallocated_payments())

    except sqlite3.Error as error:

        print("Database Error:", error)
