
import sqlite3
from decimal import Decimal
from datetime import datetime

DATABASE = "reconciliation.db"


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
            paid TEXT NOT NULL DEFAULT '0'
        );

        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            customer TEXT NOT NULL,
            amount TEXT NOT NULL,
            payment_date TEXT,
            invoice_ref TEXT DEFAULT '',
            description TEXT DEFAULT '',
            allocated TEXT NOT NULL DEFAULT '0'
        );

        CREATE TABLE IF NOT EXISTS allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL,
            payment_id TEXT NOT NULL,
            amount TEXT NOT NULL,
            created_at TEXT NOT NULL,

            FOREIGN KEY(invoice_id)
                REFERENCES invoices(invoice_id),

            FOREIGN KEY(payment_id)
                REFERENCES payments(payment_id),

            UNIQUE(invoice_id, payment_id)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL,
            payment_id TEXT NOT NULL,
            status TEXT NOT NULL,
            explanation TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_payment_customer
        ON payments(customer);

        CREATE INDEX IF NOT EXISTS idx_invoice_customer
        ON invoices(customer);

        """)

    print("Database initialized successfully!")


# =====================================
# INSERT INVOICE
# =====================================

def add_invoice(invoice_id, customer, amount, invoice_date=""):

    amount = Decimal(str(amount)).quantize(Decimal("0.01"))

    if not invoice_id or not customer or amount <= 0:
        raise ValueError("Invalid invoice information")

    with get_connection() as conn:

        conn.execute("""
            INSERT INTO invoices
            (invoice_id, customer, amount, invoice_date, paid)
            VALUES (?, ?, ?, ?, ?)
        """, (
            invoice_id,
            customer,
            str(amount),
            invoice_date,
            "0.00"
        ))

    return True


# =====================================
# INSERT PAYMENT
# =====================================

def add_payment(
    payment_id,
    customer,
    amount,
    payment_date="",
    invoice_ref="",
    description=""
):

    amount = Decimal(str(amount)).quantize(Decimal("0.01"))

    if not payment_id or not customer or amount <= 0:
        raise ValueError("Invalid payment information")

    with get_connection() as conn:

        conn.execute("""
            INSERT INTO payments
            (
                payment_id,
                customer,
                amount,
                payment_date,
                invoice_ref,
                description,
                allocated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            payment_id,
            customer,
            str(amount),
            payment_date,
            invoice_ref,
            description,
            "0.00"
        ))

    return True


# =====================================
# GET ALL INVOICES
# =====================================

def get_all_invoices():

    with get_connection() as conn:

        records = conn.execute("""
            SELECT * FROM invoices
            ORDER BY invoice_date
        """).fetchall()

    return [dict(row) for row in records]


# =====================================
# GET ALL PAYMENTS
# =====================================

def get_all_payments():

    with get_connection() as conn:

        records = conn.execute("""
            SELECT * FROM payments
            ORDER BY payment_date
        """).fetchall()

    return [dict(row) for row in records]


# =====================================
# CALCULATE OUTSTANDING BALANCE
# =====================================

def get_outstanding_balance(invoice_id):

    with get_connection() as conn:

        invoice = conn.execute("""
            SELECT amount, paid
            FROM invoices
            WHERE invoice_id = ?
        """, (invoice_id,)).fetchone()

    if not invoice:
        raise ValueError("Invoice not found")

    return (
        Decimal(invoice["amount"]) -
        Decimal(invoice["paid"])
    )


# =====================================
# CALCULATE UNALLOCATED PAYMENT
# =====================================

def get_unallocated_payment(payment_id):

    with get_connection() as conn:

        payment = conn.execute("""
            SELECT amount, allocated
            FROM payments
            WHERE payment_id = ?
        """, (payment_id,)).fetchone()

    if not payment:
        raise ValueError("Payment not found")

    return (
        Decimal(payment["amount"]) -
        Decimal(payment["allocated"])
    )


# =====================================
# CONFIRM PAYMENT ALLOCATION
# =====================================

def allocate_payment(invoice_id, payment_id, amount):

    amount = Decimal(str(amount)).quantize(Decimal("0.01"))

    if amount <= 0:
        raise ValueError("Allocation must be positive")

    with get_connection() as conn:

        conn.execute("BEGIN IMMEDIATE")

        invoice = conn.execute("""
            SELECT * FROM invoices
            WHERE invoice_id = ?
        """, (invoice_id,)).fetchone()

        payment = conn.execute("""
            SELECT * FROM payments
            WHERE payment_id = ?
        """, (payment_id,)).fetchone()

        if not invoice or not payment:
            raise ValueError("Invoice or payment not found")

        invoice_balance = (
            Decimal(invoice["amount"]) -
            Decimal(invoice["paid"])
        )

        payment_balance = (
            Decimal(payment["amount"]) -
            Decimal(payment["allocated"])
        )

        if amount > invoice_balance:
            raise ValueError("Invoice balance exceeded")

        if amount > payment_balance:
            raise ValueError("Payment already allocated or insufficient")

        conn.execute("""
            INSERT INTO allocations
            (invoice_id, payment_id, amount, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            invoice_id,
            payment_id,
            str(amount),
            datetime.now().isoformat()
        ))

        conn.execute("""
            UPDATE invoices
            SET paid = ?
            WHERE invoice_id = ?
        """, (
            str(Decimal(invoice["paid"]) + amount),
            invoice_id
        ))

        conn.execute("""
            UPDATE payments
            SET allocated = ?
            WHERE payment_id = ?
        """, (
            str(Decimal(payment["allocated"]) + amount),
            payment_id
        ))

    return True


# =====================================
# SAVE USER DECISION
# =====================================

def save_decision(
    invoice_id,
    payment_id,
    status,
    explanation=""
):

    if status not in ("Confirmed", "Rejected"):
        raise ValueError("Invalid decision status")

    with get_connection() as conn:

        conn.execute("""
            INSERT INTO decisions
            (
                invoice_id,
                payment_id,
                status,
                explanation,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            invoice_id,
            payment_id,
            status,
            explanation,
            datetime.now().isoformat()
        ))

    return True


# =====================================
# GET RECONCILIATION STATISTICS
# =====================================

def get_statistics():

    with get_connection() as conn:

        invoices = conn.execute("""
            SELECT amount, paid FROM invoices
        """).fetchall()

        payments = conn.execute("""
            SELECT amount, allocated FROM payments
        """).fetchall()

        total_invoice = sum(
            (Decimal(row["amount"]) for row in invoices),
            Decimal("0")
        )

        total_paid = sum(
            (Decimal(row["paid"]) for row in invoices),
            Decimal("0")
        )

        total_payments = sum(
            (Decimal(row["amount"]) for row in payments),
            Decimal("0")
        )

        total_allocated = sum(
            (Decimal(row["allocated"]) for row in payments),
            Decimal("0")
        )

    return {
        "total_invoices": len(invoices),
        "total_payments": len(payments),
        "total_invoice_amount": str(total_invoice),
        "total_paid": str(total_paid),
        "outstanding_balance": str(total_invoice - total_paid),
        "unallocated_payments": str(
            total_payments - total_allocated
        )
    }


# =====================================
# DATABASE TEST
# =====================================

if __name__ == "__main__":

    initialize_database()

    print("\nDatabase Statistics:")

    print(get_statistics())
