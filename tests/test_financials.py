import os
import sys
import pytest
from decimal import Decimal

# Ensure backend path is available
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import (
    reset_database,
    get_connection,
    allocate_payment,
    get_invoice_balance,
    get_payment_balance,
    to_decimal
)


@pytest.fixture(autouse=True)
def clean_db():
    reset_database()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO invoices (invoice_id, customer, amount, invoice_date, paid)
            VALUES ('INV-TEST-1', 'Test Customer', '1000.00', '2026-10-01', '0.00')
        """)
        conn.execute("""
            INSERT INTO payments (payment_id, customer, amount, payment_date, allocated)
            VALUES ('TXN-TEST-1', 'Test Customer', '600.00', '2026-10-02', '0.00')
        """)


def test_partial_allocation_and_balances():
    # Allocate 600 from payment of 600 to invoice of 1000
    allocate_payment("INV-TEST-1", "TXN-TEST-1", "600.00", "Partial match test")

    with get_connection() as conn:
        inv = dict(conn.execute("SELECT * FROM invoices WHERE invoice_id = 'INV-TEST-1'").fetchone())
        pay = dict(conn.execute("SELECT * FROM payments WHERE payment_id = 'TXN-TEST-1'").fetchone())

    assert to_decimal(inv["paid"]) == Decimal("600.00")
    assert get_invoice_balance(inv) == Decimal("400.00")
    assert to_decimal(pay["allocated"]) == Decimal("600.00")
    assert get_payment_balance(pay) == Decimal("0.00")


def test_prevent_double_allocation():
    # First allocation succeeds
    allocate_payment("INV-TEST-1", "TXN-TEST-1", "600.00")

    # Second allocation of same payment must fail because payment balance is exhausted
    with pytest.raises(ValueError, match="exceeds available payment balance"):
        allocate_payment("INV-TEST-1", "TXN-TEST-1", "600.00")


def test_allocation_exceeding_invoice_balance():
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO payments (payment_id, customer, amount, payment_date, allocated)
            VALUES ('TXN-LARGE', 'Test Customer', '5000.00', '2026-10-02', '0.00')
        """)

    # Try to allocate 5000 to an invoice with balance 1000
    with pytest.raises(ValueError, match="exceeds outstanding invoice balance"):
        allocate_payment("INV-TEST-1", "TXN-LARGE", "5000.00")

