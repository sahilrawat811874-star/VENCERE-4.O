import os
import sys
import pandas as pd
import pytest

# Ensure backend path is available
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import (
    validate_invoice_row,
    validate_payment_row,
    import_invoices_from_df,
    import_payments_from_df,
    reset_database,
    get_import_errors
)


def test_validate_invoice_row_valid():
    row = {"invoice_id": "INV-101", "customer": "ABC Corp", "amount": "150.00", "invoice_date": "2026-10-01"}
    is_valid, errs = validate_invoice_row(row)
    assert is_valid is True
    assert len(errs) == 0


def test_validate_invoice_row_invalid():
    # Missing customer and negative amount
    row = {"invoice_id": "INV-ERR", "customer": "", "amount": "-150.00", "invoice_date": "2026-10-01"}
    is_valid, errs = validate_invoice_row(row)
    assert is_valid is False
    assert any("customer" in e.lower() for e in errs)
    assert any("positive" in e.lower() for e in errs)


def test_validate_payment_row_invalid_amount():
    row = {"payment_id": "TXN-ERR", "customer": "ABC", "amount": "NaN_NOT_A_NUMBER"}
    is_valid, errs = validate_payment_row(row)
    assert is_valid is False
    assert any("monetary amount" in e.lower() for e in errs)


def test_import_df_catches_errors():
    reset_database()
    df = pd.DataFrame([
        {"invoice_id": "INV-OK", "customer": "Good Client", "amount": "500.00", "invoice_date": "2026-10-01"},
        {"invoice_id": "INV-BAD", "customer": "", "amount": "invalid", "invoice_date": "2026-10-01"}
    ])
    inserted, errors = import_invoices_from_df(df)
    assert inserted == 1
    assert len(errors) == 1
    assert errors[0]["record_id"] == "INV-BAD"

    db_errors = get_import_errors()
    assert len(db_errors) == 1

