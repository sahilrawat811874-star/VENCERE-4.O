import os
import sys
import pandas as pd
import streamlit as st
from decimal import Decimal

# Ensure backend modules are reachable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
from database import (
    initialize_database,
    reset_database,
    import_invoices_from_df,
    import_payments_from_df,
    get_statistics,
    get_all_invoices,
    get_all_payments,
    get_unmatched_invoices,
    get_unallocated_payments,
    get_allocations,
    get_decisions,
    get_import_errors,
    allocate_payment,
    reject_match,
    export_reconciliation_report_df,
    to_decimal
)
from matching import generate_suggestions
from benchmark import run_benchmark

# Page Configuration
st.set_page_config(
    page_title="Smart Invoice Reconciliation System",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize DB on load
initialize_database()

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 15px;
        border-left: 5px solid #1f77b4;
    }
    .badge-high {
        background-color: #d4edda;
        color: #155724;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: 600;
    }
    .badge-medium {
        background-color: #fff3cd;
        color: #856404;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: 600;
    }
    .badge-low {
        background-color: #f8d7da;
        color: #721c24;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: 600;
    }
    .badge-ambiguous {
        background-color: #e2e3e5;
        color: #383d41;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# SIDEBAR
# ==========================================

st.sidebar.title("⚖️ Reconciliation System")
st.sidebar.markdown("**AI-Powered Invoice & Payment Matching**")
st.sidebar.write("---")

st.sidebar.subheader("Quick Dataset Setup")
sample_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
inv_sample = os.path.join(sample_dir, "invoices.csv")
pay_sample = os.path.join(sample_dir, "payments.csv")

if st.sidebar.button("🚀 Load Labeled Sample Dataset", use_container_width=True):
    if os.path.exists(inv_sample) and os.path.exists(pay_sample):
        reset_database()
        df_inv = pd.read_csv(inv_sample)
        df_pay = pd.read_csv(pay_sample)
        i_cnt, i_err = import_invoices_from_df(df_inv)
        p_cnt, p_err = import_payments_from_df(df_pay)
        st.sidebar.success(f"Loaded {i_cnt} Invoices & {p_cnt} Payments!")
        if i_err or p_err:
            st.sidebar.warning(f"Caught {len(i_err) + len(p_err)} invalid rows (recorded in Validation Log)")
        st.rerun()
    else:
        st.sidebar.error("Sample files not found in sample_data directory.")

if st.sidebar.button("🔄 Reset Database", use_container_width=True):
    reset_database()
    st.sidebar.info("Database reset to clean state.")
    st.rerun()

st.sidebar.write("---")
stats = get_statistics()
st.sidebar.markdown(f"**Total Invoices:** {stats['total_invoices']}")
st.sidebar.markdown(f"**Total Payments:** {stats['total_payments']}")
st.sidebar.markdown(f"**Allocations Made:** {stats['allocations_count']}")
st.sidebar.markdown(f"**Decisions Logged:** {stats['decisions_count']}")
st.sidebar.caption("Financial precision: Python Decimal (0.01)")


# ==========================================
# MAIN INTERFACE TABS
# ==========================================

st.title("⚖️ Smart Invoice & Payment Reconciliation")
st.markdown("Automated evidence-based matching, ambiguity detection, and reviewable reconciliation workflow for small businesses.")

tabs = st.tabs([
    "📊 Financial Overview",
    "💡 Suggested Matches",
    "📁 Upload & Validate CSV",
    "🔍 Unmatched & Unallocated",
    "🛠️ Manual Assignment",
    "📈 Benchmark & Accuracy",
    "📑 Report & Audit Trail"
])


# ==========================================
# TAB 1: FINANCIAL OVERVIEW
# ==========================================
with tabs[0]:
    st.header("Financial Reconciliation Dashboard")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Invoiced", f"₹{stats['total_invoice_amount']}", delta=f"{stats['total_invoices']} Invoices")
    with col2:
        st.metric("Confirmed Paid", f"₹{stats['total_paid_amount']}", delta=f"{stats['fully_paid_invoices']} Fully Paid")
    with col3:
        st.metric("Outstanding Balance", f"₹{stats['outstanding_balance']}")
    with col4:
        st.metric("Unallocated Payments", f"₹{stats['unallocated_payments']}", delta=f"{stats['total_payments']} Payments Received")

    # Reconciliation Progress
    total_inv_d = to_decimal(stats["total_invoice_amount"])
    paid_d = to_decimal(stats["total_paid_amount"])
    progress = float(paid_d / total_inv_d) if total_inv_d > Decimal("0.00") else 0.0
    st.write("")
    st.markdown(f"**Reconciliation Progress:** {progress * 100:.1f}%")
    st.progress(min(1.0, progress))

    st.write("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Recent Invoices")
        inv_df = pd.DataFrame(get_all_invoices())
        if not inv_df.empty:
            st.dataframe(inv_df[["invoice_id", "customer", "amount", "paid", "invoice_date"]], use_container_width=True)
        else:
            st.info("No invoices loaded yet. Upload CSV or click 'Load Labeled Sample Dataset'.")

    with c2:
        st.subheader("Recent Payments")
        pay_df = pd.DataFrame(get_all_payments())
        if not pay_df.empty:
            st.dataframe(pay_df[["payment_id", "customer", "amount", "allocated", "payment_date", "invoice_ref"]], use_container_width=True)
        else:
            st.info("No payments loaded yet.")


# ==========================================
# TAB 2: SUGGESTED MATCHES & REVIEW
# ==========================================
with tabs[1]:
    st.header("Match Suggestions & Review Queue")
    st.markdown("Matches identified using **Invoice References**, **Customer Similarity (RapidFuzz)**, **Monetary Balances (Decimal)**, and **Transaction Dates**.")

    suggestions = generate_suggestions()

    if not suggestions:
        st.success("🎉 No pending suggested matches found. All reconcilable items may have already been matched!")
    else:
        # Filter controls
        f_col1, f_col2 = st.columns([1, 2])
        with f_col1:
            conf_filter = st.selectbox("Filter Confidence", ["All", "High", "Medium", "Low"])
        with f_col2:
            status_filter = st.selectbox("Filter Status", ["All", "Ready to Confirm", "Review Required", "Ambiguous - Review Required"])

        filtered = suggestions
        if conf_filter != "All":
            filtered = [s for s in filtered if s["confidence"] == conf_filter]
        if status_filter != "All":
            filtered = [s for s in filtered if s["status"] == status_filter]

        st.info(f"Showing **{len(filtered)}** suggestion(s)")

        for idx, item in enumerate(filtered):
            score = item["confidence_score"]
            conf = item["confidence"]
            status = item["status"]
            badge_class = "badge-high" if conf == "High" else ("badge-medium" if conf == "Medium" else "badge-low")
            if "Ambiguous" in status:
                badge_class = "badge-ambiguous"

            with st.expander(f"⚖️ Suggestion #{idx+1}: {item['invoice_id']} ⟷ {item['payment_id']} (Score: {score}% - {conf})", expanded=(idx < 3)):
                sc1, sc2, sc3 = st.columns(3)
                with sc1:
                    st.markdown("**Invoice Details**")
                    st.write(f"- ID: `{item['invoice_id']}`")
                    st.write(f"- Customer: **{item['invoice_customer']}**")
                    st.write(f"- Total: ₹{item['invoice_amount']}")
                    st.write(f"- Outstanding: **₹{item['invoice_outstanding']}**")
                with sc2:
                    st.markdown("**Payment Details**")
                    st.write(f"- ID: `{item['payment_id']}`")
                    st.write(f"- Customer: **{item['payment_customer']}**")
                    st.write(f"- Total: ₹{item['payment_amount']}")
                    st.write(f"- Remaining: **₹{item['payment_remaining']}**")
                with sc3:
                    st.markdown("**Evaluation & Status**")
                    st.markdown(f"Status: `{status}`")
                    st.markdown(f"Confidence: **{score}% ({conf})**")
                    st.markdown(f"Suggested Allocation: **₹{item['suggested_allocation']}**")

                st.markdown("**Supporting Evidence:**")
                for ev in item["evidence"]:
                    st.markdown(f"- 🔎 {ev}")

                # Action buttons
                act_c1, act_c2, act_c3 = st.columns([1, 1, 2])
                with act_c1:
                    alloc_val = st.text_input(f"Allocate Amount", value=item["suggested_allocation"], key=f"alloc_{item['invoice_id']}_{item['payment_id']}")
                with act_c2:
                    st.write("")
                    st.write("")
                    if st.button("✅ Confirm Match", key=f"conf_{item['invoice_id']}_{item['payment_id']}"):
                        try:
                            evidence_str = "; ".join(item["evidence"])
                            allocate_payment(item["invoice_id"], item["payment_id"], alloc_val, evidence_str)
                            st.success(f"Allocated ₹{alloc_val} from {item['payment_id']} to {item['invoice_id']}!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Allocation error: {e}")
                with act_c3:
                    st.write("")
                    st.write("")
                    if st.button("❌ Reject Match", key=f"rej_{item['invoice_id']}_{item['payment_id']}"):
                        reject_match(item["invoice_id"], item["payment_id"], "Rejected by reviewer in queue")
                        st.warning(f"Rejected pair {item['invoice_id']} ⟷ {item['payment_id']}.")
                        st.rerun()


# ==========================================
# TAB 3: UPLOAD & VALIDATE CSV
# ==========================================
with tabs[2]:
    st.header("Import CSV Files & Data Validation")
    st.markdown("Upload invoices and payments from CSV files. Incomplete or invalid records are captured and flagged.")

    up_c1, up_c2 = st.columns(2)
    with up_c1:
        st.subheader("Upload Invoices CSV")
        inv_file = st.file_uploader("Choose Invoices CSV", type=["csv"], key="inv_uploader")
        if inv_file:
            try:
                df = pd.read_csv(inv_file)
                inserted, errs = import_invoices_from_df(df)
                st.success(f"Successfully imported {inserted} valid invoice(s)!")
                if errs:
                    st.warning(f"Detected {len(errs)} invalid invoice record(s)")
            except Exception as e:
                st.error(f"Error reading invoice file: {e}")

    with up_c2:
        st.subheader("Upload Payments CSV")
        pay_file = st.file_uploader("Choose Payments CSV", type=["csv"], key="pay_uploader")
        if pay_file:
            try:
                df = pd.read_csv(pay_file)
                inserted, errs = import_payments_from_df(df)
                st.success(f"Successfully imported {inserted} valid payment(s)!")
                if errs:
                    st.warning(f"Detected {len(errs)} invalid payment record(s)")
            except Exception as e:
                st.error(f"Error reading payment file: {e}")

    st.write("---")
    st.subheader("Validation Error Log (Invalid/Incomplete Records)")
    err_records = get_import_errors()
    if err_records:
        df_errs = pd.DataFrame(err_records)
        st.dataframe(df_errs[["id", "file_type", "record_id", "error_reason", "created_at"]], use_container_width=True)
    else:
        st.info("No validation errors recorded.")


# ==========================================
# TAB 4: UNMATCHED & UNALLOCATED
# ==========================================
with tabs[3]:
    st.header("Unmatched Invoices & Unallocated Payments")
    st.markdown("Track records that have not been reconciled or still hold remaining monetary balance.")

    un_c1, un_c2 = st.columns(2)
    with un_c1:
        st.subheader("Unmatched / Open Invoices")
        unmatched_invoices = get_unmatched_invoices()
        if unmatched_invoices:
            st.metric("Open Invoices Count", len(unmatched_invoices))
            df_un_inv = pd.DataFrame(unmatched_invoices)
            st.dataframe(df_un_inv[["invoice_id", "customer", "amount", "paid", "outstanding", "invoice_date"]], use_container_width=True)
        else:
            st.success("All invoices are fully paid!")

    with un_c2:
        st.subheader("Unallocated / Surplus Payments")
        unallocated_payments = get_unallocated_payments()
        if unallocated_payments:
            st.metric("Unallocated Payments Count", len(unallocated_payments))
            df_un_pay = pd.DataFrame(unallocated_payments)
            st.dataframe(df_un_pay[["payment_id", "customer", "amount", "allocated", "unallocated", "payment_date", "invoice_ref", "description"]], use_container_width=True)
        else:
            st.success("All payments are fully allocated!")


# ==========================================
# TAB 5: MANUAL ASSIGNMENT
# ==========================================
with tabs[4]:
    st.header("Manual Match Assignment")
    st.markdown("Manually pair any open invoice with any unallocated payment with real-time balance safeguards.")

    open_invoices = get_unmatched_invoices()
    open_payments = get_unallocated_payments()

    if not open_invoices or not open_payments:
        st.info("Manual assignment requires at least one open invoice and one unallocated payment.")
    else:
        inv_choices = {f"{i['invoice_id']} | {i['customer']} (Bal: ₹{i['outstanding']})": i for i in open_invoices}
        pay_choices = {f"{p['payment_id']} | {p['customer']} (Bal: ₹{p['unallocated']})": p for p in open_payments}

        m_col1, m_col2 = st.columns(2)
        with m_col1:
            sel_inv_label = st.selectbox("Select Invoice", list(inv_choices.keys()))
            selected_inv = inv_choices[sel_inv_label]
        with m_col2:
            sel_pay_label = st.selectbox("Select Payment", list(pay_choices.keys()))
            selected_pay = pay_choices[sel_pay_label]

        max_alloc = min(to_decimal(selected_inv["outstanding"]), to_decimal(selected_pay["unallocated"]))
        st.markdown(f"**Maximum Permissible Allocation:** `₹{max_alloc}`")

        man_c1, man_c2 = st.columns([1, 2])
        with man_c1:
            man_amount = st.text_input("Allocation Amount", value=str(max_alloc))
        with man_c2:
            man_reason = st.text_input("Reviewer Audit Reason", value="Manual allocation confirmed by user")

        if st.button("Confirm Manual Allocation", type="primary"):
            try:
                allocate_payment(selected_inv["invoice_id"], selected_pay["payment_id"], man_amount, man_reason)
                st.success(f"Successfully allocated ₹{man_amount} from {selected_pay['payment_id']} to {selected_inv['invoice_id']}!")
                st.rerun()
            except Exception as e:
                st.error(f"Allocation failed: {e}")


# ==========================================
# TAB 6: BENCHMARK & ACCURACY
# ==========================================
with tabs[5]:
    st.header("Algorithm Benchmark against Labeled Ground Truth")
    st.markdown("Measures matching precision, recall, F1 score, ambiguity detection, and unresolved rates against `sample_data/ground_truth.csv`.")

    if st.button("⚡ Run Live Benchmark Evaluation", type="primary"):
        with st.spinner("Running benchmark against labeled ground truth..."):
            try:
                summary, df_details = run_benchmark()

                b1, b2, b3, b4 = st.columns(4)
                with b1:
                    st.metric("Overall Accuracy", f"{summary['accuracy']}%")
                with b2:
                    st.metric("Precision", f"{summary['precision']}%")
                with b3:
                    st.metric("Recall", f"{summary['recall']}%")
                with b4:
                    st.metric("F1 Score", f"{summary['f1_score']}%")

                b5, b6, b7, b8 = st.columns(4)
                with b5:
                    st.metric("Ground Truth Records", summary["total_ground_truth_records"])
                with b6:
                    st.metric("Ambiguous Flagged", summary["ambiguous_flagged"])
                with b7:
                    st.metric("Unresolved Invoices", summary["unresolved_invoices_count"])
                with b8:
                    st.metric("Validation Errors Caught", summary["import_errors_caught"])

                st.write("---")
                st.subheader("Detailed Evaluation Table")
                st.dataframe(df_details, use_container_width=True)
            except Exception as e:
                st.error(f"Benchmark error: {e}")


# ==========================================
# TAB 7: REPORT & AUDIT TRAIL
# ==========================================
with tabs[6]:
    st.header("Reconciliation Report & Audit Trail")
    st.markdown("Export complete reconciliation results including allocations, rejections, and unresolved records.")

    df_report = export_reconciliation_report_df()

    if not df_report.empty:
        csv_data = df_report.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Reconciliation Report (CSV)",
            data=csv_data,
            file_name="reconciliation_report.csv",
            mime="text/csv",
            type="primary"
        )
        st.write("")
        st.dataframe(df_report, use_container_width=True)
    else:
        st.info("No records available to export yet.")

