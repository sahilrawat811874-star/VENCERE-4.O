import os
import sys
import pytest
from decimal import Decimal

# Ensure backend path is available
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from matching import (
    compare_customer,
    compare_dates,
    compare_amounts,
    calculate_match,
    extract_reference
)
from database import to_decimal


# Test 1: Convert amount into Decimal
def test_to_decimal():
    assert to_decimal("1000.50") == Decimal("1000.50")
    assert to_decimal("25,000.00") == Decimal("25000.00")
    assert to_decimal("₹500.25") == Decimal("500.25")


# Test 2: Invalid amount should raise an error
def test_invalid_decimal():
    with pytest.raises(Exception):
        to_decimal("invalid_amount")


# Test 3: Customer similarity matching
def test_compare_customer_exact_and_fuzzy():
    # Exact
    assert compare_customer("Rahul Sharma", "Rahul Sharma") == 100
    # Suffix removal (Pvt Ltd vs bare)
    assert compare_customer("Sharma Enterprises Pvt Ltd", "Sharma Enterprises") >= 85
    # Token reordering
    assert compare_customer("Apex Technologies", "Technologies Apex") >= 85
    # Different customers
    assert compare_customer("Rahul Sharma", "Amit Verma") < 50


# Test 4: Reference extraction from description
def test_extract_reference():
    refs = extract_reference("NEFT TRF INV-1003 APEX")
    assert "INV1003" in refs


# Test 5: Date comparison rules
def test_compare_dates():
    score, reason = compare_dates("2026-10-01", "2026-10-03")
    assert score > 0
    assert "within" in reason.lower()

    # Predating payment
    score_predate, reason_predate = compare_dates("2026-10-20", "2026-10-01")
    assert score_predate < 0
    assert "predates" in reason_predate.lower()


# Test 6: Amount comparison rules
def test_compare_amounts_exact_and_partial():
    # Exact balance
    score, reason = compare_amounts("1000.00", "1000.00")
    assert score > 20
    assert "Exact" in reason

    # Partial payment
    score_p, reason_p = compare_amounts("1000.00", "400.00")
    assert score_p > 0
    assert "partial" in reason_p.lower()

    # Excess payment
    score_e, reason_e = compare_amounts("1000.00", "1500.00")
    assert score_e == 0
    assert "exceeds" in reason_e.lower()


# Test 7: Full match calculation structure & confidence
def test_calculate_match():
    invoice = {
        "invoice_id": "INV-1001",
        "customer": "Rahul Traders",
        "amount": "25000.00",
        "paid": "0.00",
        "invoice_date": "2026-10-01"
    }
    payment = {
        "payment_id": "TXN-2001",
        "customer": "Rahul Traders",
        "amount": "25000.00",
        "allocated": "0.00",
        "payment_date": "2026-10-02",
        "invoice_ref": "INV-1001",
        "description": "Invoice payment"
    }

    result = calculate_match(invoice, payment)
    assert isinstance(result, dict)
    assert "score" in result
    assert "confidence" in result
    assert "evidence" in result
    assert result["score"] >= 80
    assert result["confidence"] == "High"
    assert len(result["evidence"]) >= 3
