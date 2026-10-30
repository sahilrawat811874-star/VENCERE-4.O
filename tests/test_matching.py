
import pytest
from decimal import Decimal

from matching import (
    to_decimal,
    compare_customer,
    compare_dates,
    compare_amounts,
    calculate_match
)


# Test 1: Convert amount into Decimal
def test_to_decimal():
    assert to_decimal("1000.50") == Decimal("1000.50")


# Test 2: Invalid amount should raise an error
def test_invalid_decimal():
    with pytest.raises(Exception):
        to_decimal("invalid")


# Test 3: Same customer should get a high similarity score
def test_compare_customer():
    score = compare_customer("Rahul Sharma", "Rahul Sharma")
    assert score >= 90


# Test 4: Different customers should get a lower score
def test_different_customer():
    score = compare_customer("Rahul Sharma", "Amit Verma")
    assert score < 90


# Test 5: Same date should get maximum date score
def test_compare_dates():
    score = compare_dates("2026-10-01", "2026-10-01")
    assert score == 10


# Test 6: Exact amount should get maximum amount score
def test_compare_amounts_exact():
    score, reason = compare_amounts(
        Decimal("1000"),
        Decimal("1000")
    )

    assert score == 20
    assert "Exact" in reason


# Test 7: Partial payment should be recognized
def test_compare_amounts_partial():
    score, reason = compare_amounts(
        Decimal("1000"),
        Decimal("500")
    )

    assert score == 12
    assert "Partial" in reason


# Test 8: Payment greater than invoice balance
def test_compare_amounts_excess():
    score, reason = compare_amounts(
        Decimal("1000"),
        Decimal("1500")
    )

    assert score == 0


# Test 9: Matching score should be within valid range
def test_calculate_match():
    invoice = {
        "invoice_id": "INV-101",
        "customer": "Rahul Sharma",
        "amount": "1000",
        "invoice_date": "2026-10-01",
        "paid": "0"
    }

    payment = {
        "payment_id": "PAY-101",
        "customer": "Rahul Sharma",
        "amount": "1000",
        "payment_date": "2026-10-01",
        "invoice_ref": "INV-101",
        "description": "Invoice payment"
    }

    score, reasons = calculate_match(invoice, payment)

    assert 0 <= score <= 100
    assert score > 0
    assert len(reasons) > 0
