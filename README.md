# ⚖️ Smart Invoice & Payment Reconciliation System

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Interface-Streamlit-red.svg)](https://streamlit.io/)
[![Testing](https://img.shields.io/badge/Tests-pytest-green.svg)](https://pytest.org/)
[![Database](https://img.shields.io/badge/Database-SQLite-lightgrey.svg)](https://sqlite.org/)

An automated, transparent, and reviewable financial reconciliation prototype built for small businesses to reconcile disparate invoice and payment CSV records with mathematical integrity and explainable recommendations.

---

## 📌 Problem Overview
Small businesses frequently maintain invoices and payment transactions across disconnected systems or spreadsheets. Variations in customer names, missing invoice numbers, identical amounts, and ambiguous descriptions often result in lost hours investigating payment statuses and risk of accounting errors.

This solution provides a complete end-to-end reconciliation workflow:
1. **Import & Validate:** Parse CSV records and flag invalid/incomplete entries.
2. **Explainable Matching Engine:** Evidence-based scoring combining invoice references, customer fuzzy matching (RapidFuzz), date proximity, and monetary balances.
3. **Ambiguity & Duplicate Safeguard:** Flags multiple candidate matches and guarantees a payment is never allocated more than once using `Python Decimal`.
4. **Interactive Dashboard:** Streamlit interface to review, confirm, reject, or manually assign matches.
5. **Benchmark & Evaluation:** Measures matching precision, recall, and unresolved rate against a labeled sample dataset.
6. **Exportable Audit Report:** Complete CSV export with allocations, rejections, and unresolved records.

---

## 🛠️ Core Tech Stack
- **Processing & Financial Logic:** `Python` & `pandas` (CSV normalization and data validation), `Python Decimal` (exact monetary balance calculations without floating-point errors).
- **Matching & Storage:** `RapidFuzz` (token sort/set and suffix-normalized fuzzy similarity), `SQLite` (transactional integrity with `BEGIN IMMEDIATE` to prevent double counting).
- **Interface & Verification:** `Streamlit` (interactive review queue and KPI dashboard), `pytest` (rule verification, decimal precision, and error handling).

---

## 📂 Project Structure
```text
WENCERE/
├── backend/
│   ├── database.py         # SQLite schema, transaction logic, and CSV imports
│   ├── matching.py         # Evidence-based matching engine & ambiguity detection
│   └── app.py              # Optional Flask REST API
├── frontend/               # Optional static HTML/CSS/JS frontend
├── sample_data/
│   ├── invoices.csv        # Sample invoices with valid and edge cases
│   ├── payments.csv        # Sample payments (exact, fuzzy, partial, ambiguous)
│   └── ground_truth.csv    # Labeled ground truth for precision/recall benchmark
├── tests/
│   ├── test_matching.py    # Matching rules, customer similarity, date rules
│   ├── test_financials.py  # Decimal accuracy & double-allocation safeguards
│   └── test_validation.py  # CSV validation and malformed record detection
├── benchmark.py            # Precision, Recall, and Accuracy benchmark runner
├── streamlit_app.py        # Primary interactive Streamlit dashboard
├── requirements.txt        # Python dependencies
└── README.md
```

---

## 🚀 How to Run

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch the Streamlit Dashboard (Recommended)
```bash
streamlit run streamlit_app.py
```
> In the sidebar, click **"🚀 Load Labeled Sample Dataset"** to populate the dashboard with sample records, ambiguous edge cases, and validation errors in 1 click!

### 3. Run Automated Tests
```bash
pytest
```

### 4. Run Benchmark Evaluation CLI
```bash
python benchmark.py
```

### 5. (Alternative) Run Flask API Backend
```bash
python backend/app.py
```

---

## 📊 Labeled Dataset Test Scenarios Covered
- **Exact Match:** Direct match via explicit invoice reference and amount (`TXN-2001` ⟷ `INV-1001`).
- **Fuzzy Customer Match:** Handles corporate suffixes like "Pvt Ltd" vs bare company name (`TXN-2002` ⟷ `INV-1002`).
- **Unstructured Description Extraction:** Extracts invoice reference embedded in bank narrative (`TXN-2003` ⟷ `INV-1003`).
- **Partial Payment:** Correctly allocates partial payment and maintains remaining invoice balance (`TXN-2004` ⟷ `INV-1004`).
- **Repeated Amounts Disambiguation:** Disambiguates identical payment amounts across distinct clients using customer similarity (`TXN-2005`, `TXN-2006`).
- **Ambiguous Match Flagging:** Detects duplicate payments and flags them for manual review rather than auto-allocating (`TXN-2007A`, `TXN-2007B`).
- **Amount Discrepancy / Bank Fee:** Identifies near matches with wire fee deductions (`TXN-2009`).
- **Unallocated Deposit:** Accurately isolates deposits without corresponding invoices (`TXN-2099`).
- **Invalid Records:** Validates and flags missing customer names, negative amounts, and non-numeric inputs (`INV-ERR1`, `INV-ERR2`, `TXN-ERR2`).

