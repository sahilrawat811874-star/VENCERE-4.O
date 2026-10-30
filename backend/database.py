import os
import sqlite3
from decimal import Decimal, InvalidOperation
from datetime import datetime
import pandas as pd

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(DB_DIR, "reconciliation.db")


# =====================================
# DATABASE CONNECTION
# =====================================

def get_connection():
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# =====================================
# CREATE DATABASE TABLES
# =====================================

def initialize_database():
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id TEXT PRIMARY KEY,
            customer TEXT NOT NULL,
            amount TEXT NOT NULL,
            invoice_date TEXT,
            paid TEXT NOT NULL DEFAULT '0.00'
        );

        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            customer TEXT NOT NULL,
            amount TEXT NOT NULL,
            payment_date TEXT,
            invoice_ref TEXT DEFAULT '',
            description TEXT DEFAULT '',
            allocated TEXT NOT NULL DEFAULT '0.00'
        );

        CREATE TABLE IF NOT EXISTS allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL,
            payment_id TEXT NOT NULL,
            amount TEXT NOT NULL,
            created_at TEXT NOT NULL,
            evidence TEXT DEFAULT '',

            FOREIGN KEY(invoice_id)
                REFERENCES invoices(invoice_id),

            FOREIGN KEY(payment_id)
                REFERENCES payments(payment_id)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL,
            payment_id TEXT NOT NULL,
            status TEXT NOT NULL,
            explanation TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS import_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_type TEXT NOT NULL,
            record_id TEXT,
            raw_data TEXT,
            error_reason TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_payment_customer ON payments(customer);
        CREATE INDEX IF NOT EXISTS idx_invoice_customer ON invoices(customer);
        CREATE INDEX IF NOT EXISTS idx_allocations_inv ON allocations(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_allocations_pay ON allocations(payment_id);
        """)
    return True


def reset_database():
    with get_connection() as conn:
        conn.executescript("""
        DROP TABLE IF EXISTS allocations;
        DROP TABLE IF EXISTS decisions;
        DROP TABLE IF EXISTS import_errors;
        DROP TABLE IF EXISTS invoices;
        DROP TABLE IF EXISTS payments;
        """)
    initialize_database()
    return True


# =====================================
# FINANCIAL HELPERS
# =====================================

def to_decimal(val) -> Decimal:
    if val is None or val == "":
        raise InvalidOperation("Empty monetary value")
    clean = str(val).replace(",", "").replace("$", "").replace("₹", "").strip()
    d = Decimal(clean)
    return d.quantize(Decimal("0.01"))


# =====================================
# DATA VALIDATION
# =====================================

def validate_invoice_row(row):
    errors = []
    inv_id = str(row.get("invoice_id", "") or "").strip()
    customer = str(row.get("customer", "") or "").strip()
    raw_amount = row.get("amount", "")
    date_val = str(row.get("invoice_date", "") or "").strip()

    if not inv_id:
        errors.append("Missing invoice_id")
    if not customer:
        errors.append("Missing customer name")

    try:
        amount = to_decimal(raw_amount)
        if amount <= Decimal("0.00"):
            errors.append(f"Amount must be positive, got {raw_amount}")
    except (InvalidOperation, ValueError, TypeError):
        errors.append(f"Invalid monetary amount: '{raw_amount}'")

    if date_val:
        try:
            # support common formats
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    datetime.strptime(date_val, fmt)
                    break
                except ValueError:
                    pass
            else:
                errors.append(f"Invalid date format: '{date_val}' (expected YYYY-MM-DD)")
        except Exception:
            errors.append(f"Invalid date: '{date_val}'")

    return (len(errors) == 0, errors)


def validate_payment_row(row):
    errors = []
    pay_id = str(row.get("payment_id", "") or "").strip()
    customer = str(row.get("customer", "") or "").strip()
    raw_amount = row.get("amount", "")
    date_val = str(row.get("payment_date", "") or "").strip()

    if not pay_id:
        errors.append("Missing payment_id")
    if not customer:
        errors.append("Missing customer name")

    try:
        amount = to_decimal(raw_amount)
        if amount <= Decimal("0.00"):
            errors.append(f"Amount must be positive, got {raw_amount}")
    except (InvalidOperation, ValueError, TypeError):
        errors.append(f"Invalid monetary amount: '{raw_amount}'")

    if date_val:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                datetime.strptime(date_val, fmt)
                break
            except ValueError:
                pass
        else:
            errors.append(f"Invalid date format: '{date_val}' (expected YYYY-MM-DD)")

    return (len(errors) == 0, errors)


# =====================================
# IMPORT INVOICES & PAYMENTS
# =====================================

def import_invoices_from_df(df):
    initialize_database()
    inserted = 0
    errors = []

    # normalize columns
    col_map = {str(c).strip().lower(): c for c in df.columns}
    inv_col = col_map.get("invoice_id", "invoice_id")
    cust_col = col_map.get("customer", "customer")
    amt_col = col_map.get("amount", "amount")
    date_col = col_map.get("invoice_date", "invoice_date")

    with get_connection() as conn:
        for idx, row in df.iterrows():
            row_dict = {
                "invoice_id": str(row.get(inv_col, "") or "").strip(),
                "customer": str(row.get(cust_col, "") or "").strip(),
                "amount": row.get(amt_col, ""),
                "invoice_date": str(row.get(date_col, "") or "").strip() if date_col in row else ""
            }
            is_valid, errs = validate_invoice_row(row_dict)
            if not is_valid:
                reason = "; ".join(errs)
                errors.append({
                    "row": idx + 1,
                    "record_id": row_dict["invoice_id"] or f"Row-{idx+1}",
                    "reason": reason
                })
                conn.execute("""
                    INSERT INTO import_errors (file_type, record_id, raw_data, error_reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, ("invoice", row_dict["invoice_id"], str(row_dict), reason, datetime.now().isoformat()))
                continue

            try:
                amt = to_decimal(row_dict["amount"])
                conn.execute("""
                    INSERT OR REPLACE INTO invoices (invoice_id, customer, amount, invoice_date, paid)
                    VALUES (?, ?, ?, ?, COALESCE((SELECT paid FROM invoices WHERE invoice_id = ?), '0.00'))
                """, (row_dict["invoice_id"], row_dict["customer"], str(amt), row_dict["invoice_date"], row_dict["invoice_id"]))
                inserted += 1
            except Exception as e:
                errors.append({"row": idx + 1, "record_id": row_dict["invoice_id"], "reason": str(e)})

    return inserted, errors


def import_payments_from_df(df):
    initialize_database()
    inserted = 0
    errors = []

    col_map = {str(c).strip().lower(): c for c in df.columns}
    pay_col = col_map.get("payment_id", "payment_id")
    cust_col = col_map.get("customer", "customer")
    amt_col = col_map.get("amount", "amount")
    date_col = col_map.get("payment_date", "payment_date")
    ref_col = col_map.get("invoice_ref", "invoice_ref")
    desc_col = col_map.get("description", "description")

    with get_connection() as conn:
        for idx, row in df.iterrows():
            row_dict = {
                "payment_id": str(row.get(pay_col, "") or "").strip(),
                "customer": str(row.get(cust_col, "") or "").strip(),
                "amount": row.get(amt_col, ""),
                "payment_date": str(row.get(date_col, "") or "").strip() if date_col in row else "",
                "invoice_ref": str(row.get(ref_col, "") or "").strip() if ref_col in row else "",
                "description": str(row.get(desc_col, "") or "").strip() if desc_col in row else ""
            }
            is_valid, errs = validate_payment_row(row_dict)
            if not is_valid:
                reason = "; ".join(errs)
                errors.append({
                    "row": idx + 1,
                    "record_id": row_dict["payment_id"] or f"Row-{idx+1}",
                    "reason": reason
                })
                conn.execute("""
                    INSERT INTO import_errors (file_type, record_id, raw_data, error_reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, ("payment", row_dict["payment_id"], str(row_dict), reason, datetime.now().isoformat()))
                continue

            try:
                amt = to_decimal(row_dict["amount"])
                conn.execute("""
                    INSERT OR REPLACE INTO payments (payment_id, customer, amount, payment_date, invoice_ref, description, allocated)
                    VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT allocated FROM payments WHERE payment_id = ?), '0.00'))
                """, (
                    row_dict["payment_id"],
                    row_dict["customer"],
                    str(amt),
                    row_dict["payment_date"],
                    row_dict["invoice_ref"],
                    row_dict["description"],
                    row_dict["payment_id"]
                ))
                inserted += 1
            except Exception as e:
                errors.append({"row": idx + 1, "record_id": row_dict["payment_id"], "reason": str(e)})

    return inserted, errors


# =====================================
# QUERY RECORDS
# =====================================

def get_all_invoices():
    with get_connection() as conn:
        records = conn.execute("SELECT * FROM invoices ORDER BY invoice_date, invoice_id").fetchall()
    return [dict(r) for r in records]


def get_all_payments():
    with get_connection() as conn:
        records = conn.execute("SELECT * FROM payments ORDER BY payment_date, payment_id").fetchall()
    return [dict(r) for r in records]


def get_invoice_balance(inv):
    amt = to_decimal(inv["amount"])
    paid = to_decimal(inv.get("paid", "0.00"))
    return (amt - paid).quantize(Decimal("0.01"))


def get_payment_balance(pay):
    amt = to_decimal(pay["amount"])
    allocated = to_decimal(pay.get("allocated", "0.00"))
    return (amt - allocated).quantize(Decimal("0.01"))


def get_unmatched_invoices():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM invoices ORDER BY invoice_id").fetchall()
    results = []
    for r in rows:
        d = dict(r)
        bal = get_invoice_balance(d)
        if bal > Decimal("0.00"):
            d["outstanding"] = str(bal)
            results.append(d)
    return results


def get_unallocated_payments():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM payments ORDER BY payment_id").fetchall()
    results = []
    for r in rows:
        d = dict(r)
        bal = get_payment_balance(d)
        if bal > Decimal("0.00"):
            d["unallocated"] = str(bal)
            results.append(d)
    return results


def get_allocations():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT a.*, i.customer as invoice_customer, p.customer as payment_customer
            FROM allocations a
            JOIN invoices i ON a.invoice_id = i.invoice_id
            JOIN payments p ON a.payment_id = p.payment_id
            ORDER BY a.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_decisions():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM decisions ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_import_errors():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM import_errors ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


# =====================================
# ALLOCATION & DECISION OPERATIONS
# =====================================

def allocate_payment(invoice_id, payment_id, amount, evidence=""):
    """
    Safely allocates funds from payment to invoice.
    Uses database transaction with strict Decimal balance verification to
    guarantee that payments are never allocated more than once or exceed balance.
    """
    alloc_amount = to_decimal(amount)
    if alloc_amount <= Decimal("0.00"):
        raise ValueError("Allocation amount must be strictly greater than 0")

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        inv_row = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
        pay_row = conn.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()

        if not inv_row or not pay_row:
            raise ValueError("Invoice or Payment record does not exist")

        inv_bal = to_decimal(inv_row["amount"]) - to_decimal(inv_row["paid"])
        pay_bal = to_decimal(pay_row["amount"]) - to_decimal(pay_row["allocated"])

        if alloc_amount > inv_bal:
            raise ValueError(
                f"Allocation amount {alloc_amount} exceeds outstanding invoice balance {inv_bal}"
            )
        if alloc_amount > pay_bal:
            raise ValueError(
                f"Allocation amount {alloc_amount} exceeds available payment balance {pay_bal}. Safeguard against double counting!"
            )

        # Record allocation
        conn.execute("""
            INSERT INTO allocations (invoice_id, payment_id, amount, created_at, evidence)
            VALUES (?, ?, ?, ?, ?)
        """, (invoice_id, payment_id, str(alloc_amount), datetime.now().isoformat(), evidence))

        # Update invoice paid
        new_paid = (to_decimal(inv_row["paid"]) + alloc_amount).quantize(Decimal("0.01"))
        conn.execute("UPDATE invoices SET paid = ? WHERE invoice_id = ?", (str(new_paid), invoice_id))

        # Update payment allocated
        new_allocated = (to_decimal(pay_row["allocated"]) + alloc_amount).quantize(Decimal("0.01"))
        conn.execute("UPDATE payments SET allocated = ? WHERE payment_id = ?", (str(new_allocated), payment_id))

        # Record decision
        conn.execute("""
            INSERT INTO decisions (invoice_id, payment_id, status, explanation, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (invoice_id, payment_id, "Confirmed", f"Allocated {alloc_amount}. Evidence: {evidence}", datetime.now().isoformat()))

    return True


def reject_match(invoice_id, payment_id, explanation="User rejected match suggestion"):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO decisions (invoice_id, payment_id, status, explanation, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (invoice_id, payment_id, "Rejected", explanation, datetime.now().isoformat()))
    return True


# =====================================
# KPI STATISTICS
# =====================================

def get_statistics():
    with get_connection() as conn:
        invoices = conn.execute("SELECT amount, paid FROM invoices").fetchall()
        payments = conn.execute("SELECT amount, allocated FROM payments").fetchall()
        allocations = conn.execute("SELECT count(*) as count FROM allocations").fetchone()
        decisions = conn.execute("SELECT count(*) as count FROM decisions").fetchone()
        errors = conn.execute("SELECT count(*) as count FROM import_errors").fetchone()

        total_inv_amt = sum((to_decimal(r["amount"]) for r in invoices), Decimal("0.00"))
        total_paid_amt = sum((to_decimal(r["paid"]) for r in invoices), Decimal("0.00"))
        total_pay_amt = sum((to_decimal(r["amount"]) for r in payments), Decimal("0.00"))
        total_allocated_amt = sum((to_decimal(r["allocated"]) for r in payments), Decimal("0.00"))

        outstanding_bal = (total_inv_amt - total_paid_amt).quantize(Decimal("0.01"))
        unallocated_pay = (total_pay_amt - total_allocated_amt).quantize(Decimal("0.01"))

        # fully paid invoices
        fully_paid_inv = sum(1 for r in invoices if to_decimal(r["amount"]) == to_decimal(r["paid"]))
        # fully allocated payments
        fully_allocated_pay = sum(1 for r in payments if to_decimal(r["amount"]) == to_decimal(r["allocated"]))

    return {
        "total_invoices": len(invoices),
        "total_payments": len(payments),
        "fully_paid_invoices": fully_paid_inv,
        "fully_allocated_payments": fully_allocated_pay,
        "total_invoice_amount": str(total_inv_amt),
        "total_paid_amount": str(total_paid_amt),
        "outstanding_balance": str(outstanding_bal),
        "total_payment_amount": str(total_pay_amt),
        "total_allocated_amount": str(total_allocated_amt),
        "unallocated_payments": str(unallocated_pay),
        "allocations_count": allocations["count"],
        "decisions_count": decisions["count"],
        "import_errors_count": errors["count"]
    }


# =====================================
# REPORT EXPORT
# =====================================

def export_reconciliation_report_df():
    """Generates structured reconciliation report including allocations, decisions, and open records."""
    rows = []

    # 1. Confirmed Allocations
    allocations = get_allocations()
    for a in allocations:
        rows.append({
            "Section": "Confirmed Allocation",
            "Invoice_ID": a["invoice_id"],
            "Payment_ID": a["payment_id"],
            "Customer": a.get("invoice_customer", ""),
            "Amount": a["amount"],
            "Status": "Allocated",
            "Evidence_Explanation": a.get("evidence", ""),
            "Timestamp": a["created_at"]
        })

    # 2. Rejections / User Decisions
    decisions = get_decisions()
    for d in decisions:
        if d["status"] == "Rejected":
            rows.append({
                "Section": "Rejected Suggestion",
                "Invoice_ID": d["invoice_id"],
                "Payment_ID": d["payment_id"],
                "Customer": "",
                "Amount": "N/A",
                "Status": "Rejected",
                "Evidence_Explanation": d.get("explanation", ""),
                "Timestamp": d["created_at"]
            })

    # 3. Unresolved Invoices
    unmatched_inv = get_unmatched_invoices()
    for inv in unmatched_inv:
        rows.append({
            "Section": "Unresolved Invoice",
            "Invoice_ID": inv["invoice_id"],
            "Payment_ID": "",
            "Customer": inv["customer"],
            "Amount": inv["outstanding"],
            "Status": "Unpaid / Outstanding Balance",
            "Evidence_Explanation": f"Original: {inv['amount']}, Paid: {inv['paid']}",
            "Timestamp": inv.get("invoice_date", "")
        })

    # 4. Unallocated Payments
    unalloc_pay = get_unallocated_payments()
    for pay in unalloc_pay:
        rows.append({
            "Section": "Unallocated Payment",
            "Invoice_ID": "",
            "Payment_ID": pay["payment_id"],
            "Customer": pay["customer"],
            "Amount": pay["unallocated"],
            "Status": "Unallocated Surplus",
            "Evidence_Explanation": f"Original: {pay['amount']}, Allocated: {pay['allocated']}. Ref: {pay.get('invoice_ref','')}. Desc: {pay.get('description','')}",
            "Timestamp": pay.get("payment_date", "")
        })

    # 5. Invalid records
    errs = get_import_errors()
    for err in errs:
        rows.append({
            "Section": "Invalid Import Record",
            "Invoice_ID": err["record_id"] if err["file_type"] == "invoice" else "",
            "Payment_ID": err["record_id"] if err["file_type"] == "payment" else "",
            "Customer": "",
            "Amount": "N/A",
            "Status": "Validation Error",
            "Evidence_Explanation": err["error_reason"],
            "Timestamp": err["created_at"]
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    initialize_database()
    print("Database ready.")
