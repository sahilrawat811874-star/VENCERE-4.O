
import os
import io
import csv
import sqlite3
import pandas as pd

from decimal import Decimal, InvalidOperation
from datetime import datetime
from flask import Flask, request, jsonify, Response
from rapidfuzz import fuzz

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(DB_DIR, "reconciliation.db")


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    with get_db() as db:

        db.executescript("""
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
            FOREIGN KEY(invoice_id) REFERENCES invoices(invoice_id),
            FOREIGN KEY(payment_id) REFERENCES payments(payment_id)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL,
            payment_id TEXT NOT NULL,
            status TEXT NOT NULL,
            explanation TEXT,
            created_at TEXT NOT NULL
        );
        """)


# ==========================================
# FINANCIAL HELPERS
# ==========================================

def money(value):
    try:
        amount = Decimal(str(value).replace(",", "").replace("₹", "").strip())
        amount = amount.quantize(Decimal("0.01"))

        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid amount")

        return amount

    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid monetary value: {value}")


def outstanding(invoice):
    return money(invoice["amount"]) - money(invoice["paid"])


def payment_remaining(payment):
    return money(payment["amount"]) - money(payment["allocated"])


def today():
    return datetime.now().isoformat(timespec="seconds")


# ==========================================
# CSV VALIDATION
# ==========================================

def read_csv(file):
    if not file or not file.filename.lower().endswith(".csv"):
        raise ValueError("Please upload a CSV file.")

    df = pd.read_csv(
        file.stream,
        dtype=str,
        keep_default_na=False
    )

    df.columns = [
        str(column).strip().lower().replace(" ", "_")
        for column in df.columns
    ]

    return df


def get_date(value):
    if not value:
        return ""

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        raise ValueError(f"Invalid date: {value}")

    return parsed.strftime("%Y-%m-%d")


# ==========================================
# IMPORT INVOICE CSV
# Required: invoice_id, customer, amount
# Optional: invoice_date
# ==========================================

@app.route("/api/upload/invoices", methods=["POST"])
def upload_invoices():

    try:
        df = read_csv(request.files.get("file"))

        required = {"invoice_id", "customer", "amount"}

        if not required.issubset(df.columns):
            return jsonify({
                "error": "Required columns: invoice_id, customer, amount"
            }), 400

        imported = 0
        errors = []

        with get_db() as db:

            for index, row in df.iterrows():

                try:
                    invoice_id = row["invoice_id"].strip()
                    customer = row["customer"].strip()
                    amount = money(row["amount"])
                    invoice_date = get_date(
                        row.get("invoice_date", "")
                    )

                    if not invoice_id or not customer or amount <= 0:
                        raise ValueError("Missing ID, customer or valid amount")

                    db.execute("""
                        INSERT INTO invoices
                        (invoice_id, customer, amount, invoice_date)
                        VALUES (?, ?, ?, ?)
                    """, (
                        invoice_id,
                        customer,
                        str(amount),
                        invoice_date
                    ))

                    imported += 1

                except (ValueError, sqlite3.IntegrityError) as error:
                    errors.append({
                        "row": int(index) + 2,
                        "error": str(error)
                    })

        return jsonify({
            "message": "Invoice import completed",
            "imported": imported,
            "invalid_records": errors
        })

    except Exception as error:
        return jsonify({"error": str(error)}), 400


# ==========================================
# IMPORT PAYMENT CSV
# Required: payment_id, customer, amount
# Optional: payment_date, invoice_ref, description
# ==========================================

@app.route("/api/upload/payments", methods=["POST"])
def upload_payments():

    try:
        df = read_csv(request.files.get("file"))

        required = {"payment_id", "customer", "amount"}

        if not required.issubset(df.columns):
            return jsonify({
                "error": "Required columns: payment_id, customer, amount"
            }), 400

        imported = 0
        errors = []

        with get_db() as db:

            for index, row in df.iterrows():

                try:
                    payment_id = row["payment_id"].strip()
                    customer = row["customer"].strip()
                    amount = money(row["amount"])

                    payment_date = get_date(
                        row.get("payment_date", "")
                    )

                    invoice_ref = row.get("invoice_ref", "").strip()
                    description = row.get("description", "").strip()

                    if not payment_id or not customer or amount <= 0:
                        raise ValueError("Missing ID, customer or valid amount")

                    db.execute("""
                        INSERT INTO payments
                        (payment_id, customer, amount, payment_date,
                         invoice_ref, description)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        payment_id,
                        customer,
                        str(amount),
                        payment_date,
                        invoice_ref,
                        description
                    ))

                    imported += 1

                except (ValueError, sqlite3.IntegrityError) as error:
                    errors.append({
                        "row": int(index) + 2,
                        "error": str(error)
                    })

        return jsonify({
            "message": "Payment import completed",
            "imported": imported,
            "invalid_records": errors
        })

    except Exception as error:
        return jsonify({"error": str(error)}), 400


# ==========================================
# SMART MATCHING ALGORITHM
# ==========================================

def match_score(invoice, payment):

    score = 0
    reasons = []

    # Invoice reference matching
    if payment["invoice_ref"].strip().lower() == \
            invoice["invoice_id"].strip().lower():

        score += 60
        reasons.append("Invoice reference matches exactly")

    # Customer name matching
    similarity = fuzz.ratio(
        invoice["customer"].lower().strip(),
        payment["customer"].lower().strip()
    )

    if similarity >= 85:
        score += 25
        reasons.append(
            f"Customer names are similar ({similarity}%)"
        )

    # Amount matching
    invoice_amount = outstanding(invoice)
    payment_amount = payment_remaining(payment)

    if invoice_amount == payment_amount:
        score += 25
        reasons.append("Payment amount matches outstanding balance")

    elif payment_amount > 0 and invoice_amount > 0:
        ratio = min(
            invoice_amount,
            payment_amount
        ) / max(invoice_amount, payment_amount)

        score += int(ratio * 15)
        reasons.append("Payment amount differs from invoice balance")

    # Transaction date matching
    if invoice["invoice_date"] and payment["payment_date"]:

        invoice_date = datetime.strptime(
            invoice["invoice_date"], "%Y-%m-%d"
        )

        payment_date = datetime.strptime(
            payment["payment_date"], "%Y-%m-%d"
        )

        days = abs((payment_date - invoice_date).days)

        if days <= 30:
            score += 10
            reasons.append("Transaction dates are within 30 days")

    return min(score, 100), reasons


@app.route("/api/suggestions", methods=["GET"])
def suggestions():

    results = []

    with get_db() as db:

        invoices = db.execute(
            "SELECT * FROM invoices"
        ).fetchall()

        payments = db.execute(
            "SELECT * FROM payments"
        ).fetchall()

        for invoice in invoices:

            if outstanding(invoice) <= 0:
                continue

            for payment in payments:

                if payment_remaining(payment) <= 0:
                    continue

                score, reasons = match_score(invoice, payment)

                if score < 45:
                    continue

                if score >= 85:
                    confidence = "High"
                elif score >= 65:
                    confidence = "Medium"
                else:
                    confidence = "Low"

                results.append({
                    "invoice_id": invoice["invoice_id"],
                    "payment_id": payment["payment_id"],
                    "customer": invoice["customer"],
                    "invoice_balance": str(outstanding(invoice)),
                    "payment_remaining": str(payment_remaining(payment)),
                    "score": score,
                    "confidence": confidence,
                    "explanation": reasons,
                    "status": "Review Required"
                })

    results.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return jsonify(results)


# ==========================================
# CONFIRM MATCH / ALLOCATE PAYMENT
# ==========================================

@app.route("/api/confirm", methods=["POST"])
def confirm_match():

    data = request.get_json(silent=True) or {}

    invoice_id = data.get("invoice_id")
    payment_id = data.get("payment_id")

    if not invoice_id or not payment_id:
        return jsonify({"error": "Invoice and payment IDs required"}), 400

    try:

        with get_db() as db:

            db.execute("BEGIN IMMEDIATE")

            invoice = db.execute(
                "SELECT * FROM invoices WHERE invoice_id = ?",
                (invoice_id,)
            ).fetchone()

            payment = db.execute(
                "SELECT * FROM payments WHERE payment_id = ?",
                (payment_id,)
            ).fetchone()

            if not invoice or not payment:
                return jsonify({"error": "Record not found"}), 404

            invoice_balance = outstanding(invoice)
            payment_balance = payment_remaining(payment)

            if invoice_balance <= 0 or payment_balance <= 0:
                return jsonify({
                    "error": "Invoice or payment is already fully allocated"
                }), 400

            amount = money(
                data.get(
                    "amount",
                    str(min(invoice_balance, payment_balance))
                )
            )

            if amount <= 0:
                return jsonify({"error": "Allocation must be positive"}), 400

            if amount > invoice_balance or amount > payment_balance:
                return jsonify({
                    "error": "Allocation exceeds available balance"
                }), 400

            new_paid = money(invoice["paid"]) + amount
            new_allocated = money(payment["allocated"]) + amount

            db.execute("""
                INSERT INTO allocations
                (invoice_id, payment_id, amount, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                invoice_id,
                payment_id,
                str(amount),
                today()
            ))

            db.execute("""
                UPDATE invoices SET paid = ?
                WHERE invoice_id = ?
            """, (str(new_paid), invoice_id))

            db.execute("""
                UPDATE payments SET allocated = ?
                WHERE payment_id = ?
            """, (str(new_allocated), payment_id))

            db.execute("""
                INSERT INTO decisions
                (invoice_id, payment_id, status, explanation, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                invoice_id,
                payment_id,
                "Confirmed",
                "User confirmed allocation",
                today()
            ))

        return jsonify({
            "message": "Payment allocated successfully",
            "allocated_amount": str(amount),
            "invoice_outstanding": str(invoice_balance - amount),
            "payment_remaining": str(payment_balance - amount)
        })

    except (ValueError, InvalidOperation) as error:
        return jsonify({"error": str(error)}), 400

    except sqlite3.Error as error:
        return jsonify({"error": str(error)}), 400


# ==========================================
# REJECT MATCH
# ==========================================

@app.route("/api/reject", methods=["POST"])
def reject_match():

    data = request.get_json(silent=True) or {}

    invoice_id = data.get("invoice_id")
    payment_id = data.get("payment_id")

    if not invoice_id or not payment_id:
        return jsonify({"error": "Both IDs are required"}), 400

    with get_db() as db:

        db.execute("""
            INSERT INTO decisions
            (invoice_id, payment_id, status, explanation, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            invoice_id,
            payment_id,
            "Rejected",
            "User rejected suggested match",
            today()
        ))

    return jsonify({"message": "Match rejected"})


# ==========================================
# DASHBOARD STATISTICS
# ==========================================

@app.route("/api/dashboard", methods=["GET"])
def dashboard():

    with get_db() as db:

        invoices = db.execute(
            "SELECT * FROM invoices"
        ).fetchall()

        payments = db.execute(
            "SELECT * FROM payments"
        ).fetchall()

        total_invoice = sum(
            (money(i["amount"]) for i in invoices),
            Decimal("0")
        )

        total_paid = sum(
            (money(i["paid"]) for i in invoices),
            Decimal("0")
        )

        total_payments = sum(
            (money(p["amount"]) for p in payments),
            Decimal("0")
        )

        total_outstanding = total_invoice - total_paid

        unallocated = sum(
            (payment_remaining(p) for p in payments),
            Decimal("0")
        )

    return jsonify({
        "total_invoices": len(invoices),
        "total_invoice_amount": str(total_invoice),
        "total_payments": str(total_payments),
        "confirmed_paid": str(total_paid),
        "outstanding_balance": str(total_outstanding),
        "unallocated_payments": str(unallocated)
    })


# ==========================================
# INVOICE AND PAYMENT LISTS
# ==========================================

@app.route("/api/invoices", methods=["GET"])
def get_invoices():

    with get_db() as db:
        records = db.execute(
            "SELECT * FROM invoices"
        ).fetchall()

    return jsonify([
        {
            "invoice_id": r["invoice_id"],
            "customer": r["customer"],
            "amount": r["amount"],
            "paid": r["paid"],
            "outstanding": str(outstanding(r)),
            "date": r["invoice_date"]
        }
        for r in records
    ])


@app.route("/api/payments", methods=["GET"])
def get_payments():

    with get_db() as db:
        records = db.execute(
            "SELECT * FROM payments"
        ).fetchall()

    return jsonify([
        {
            "payment_id": r["payment_id"],
            "customer": r["customer"],
            "amount": r["amount"],
            "allocated": r["allocated"],
            "remaining": str(payment_remaining(r)),
            "date": r["payment_date"]
        }
        for r in records
    ])


# ==========================================
# DOWNLOAD RECONCILIATION CSV REPORT
# ==========================================

@app.route("/api/report", methods=["GET"])
def report():

    with get_db() as db:

        records = db.execute("""
            SELECT
                a.invoice_id,
                i.customer,
                a.payment_id,
                a.amount,
                a.created_at
            FROM allocations a
            JOIN invoices i
            ON a.invoice_id = i.invoice_id
            ORDER BY a.id
        """).fetchall()

        unresolved = db.execute("""
            SELECT invoice_id, payment_id, status, explanation, created_at
            FROM decisions
            WHERE status = 'Rejected'
            ORDER BY id
        """).fetchall()

        invoices = db.execute(
            "SELECT * FROM invoices"
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Record Type",
            "Invoice ID",
            "Customer",
            "Payment ID",
            "Amount",
            "Status",
            "Outstanding",
            "Date",
            "Explanation"
        ])

        for r in records:

            invoice = next(
                i for i in invoices
                if i["invoice_id"] == r["invoice_id"]
            )

            writer.writerow([
                "Allocation",
                r["invoice_id"],
                r["customer"],
                r["payment_id"],
                r["amount"],
                "Confirmed",
                str(outstanding(invoice)),
                r["created_at"],
                "User confirmed allocation"
            ])

        for r in unresolved:
            writer.writerow([
                "Decision",
                r["invoice_id"],
                "",
                r["payment_id"],
                "",
                r["status"],
                "",
                r["created_at"],
                r["explanation"]
            ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=reconciliation_report.csv"
        }
    )


# ==========================================
# HOME PAGE
# ==========================================

@app.route("/")
def home():
    return """
    <h1>Smart Invoice Reconciliation API</h1>
    <p>Backend is running successfully.</p>
    <p>Use your frontend to connect to the /api endpoints.</p>
    """


# ==========================================
# START SERVER
# ==========================================

if __name__ == "__main__":

    init_db()

    print("====================================")
    print("Smart Reconciliation Backend Started")
    print("Open: http://127.0.0.1:5000")
    print("====================================")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
