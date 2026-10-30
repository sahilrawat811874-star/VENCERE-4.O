import os
import sys
import pandas as pd
from decimal import Decimal

# Ensure backend can be imported
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
from database import (
    reset_database,
    import_invoices_from_df,
    import_payments_from_df,
    get_statistics,
    get_unmatched_invoices,
    get_unallocated_payments
)
from matching import generate_suggestions


def run_benchmark(sample_dir="sample_data"):
    inv_path = os.path.join(sample_dir, "invoices.csv")
    pay_path = os.path.join(sample_dir, "payments.csv")
    truth_path = os.path.join(sample_dir, "ground_truth.csv")

    if not os.path.exists(truth_path):
        raise FileNotFoundError(f"Ground truth file not found at {truth_path}")

    # Reset DB and import sample data
    reset_database()
    df_inv = pd.read_csv(inv_path)
    df_pay = pd.read_csv(pay_path)
    df_truth = pd.read_csv(truth_path)

    inv_count, inv_errors = import_invoices_from_df(df_inv)
    pay_count, pay_errors = import_payments_from_df(df_pay)

    # Generate suggestions
    suggestions = generate_suggestions()

    # Map payment_id -> top suggestion
    top_suggestions = {}
    for s in suggestions:
        pid = s["payment_id"]
        if pid not in top_suggestions:
            top_suggestions[pid] = s

    tp = 0
    fp = 0
    fn = 0
    correct_unmatched = 0
    ambiguous_flagged = 0

    detailed_results = []

    for _, row in df_truth.iterrows():
        pid = str(row["payment_id"]).strip()
        expected_inv = str(row["expected_invoice_id"]).strip()
        match_type = str(row.get("match_type", ""))
        expected_status = str(row.get("expected_status", ""))

        suggested = top_suggestions.get(pid)
        suggested_inv = suggested["invoice_id"] if suggested else "NO_SUGGESTION"
        suggested_conf = suggested["confidence"] if suggested else "None"
        suggested_score = suggested["confidence_score"] if suggested else 0
        suggested_status = suggested["status"] if suggested else "Unmatched"

        if "Ambiguous" in suggested_status:
            ambiguous_flagged += 1

        is_match = False
        outcome = "Incorrect"

        if expected_inv == "UNMATCHED":
            if suggested is None:
                correct_unmatched += 1
                outcome = "Correct (True Negative)"
                is_match = True
            else:
                fp += 1
                outcome = "False Positive (Suggested match for unallocated payment)"
        else:
            if suggested_inv == expected_inv:
                tp += 1
                outcome = "Correct (True Positive)"
                is_match = True
            elif suggested is None:
                fn += 1
                outcome = "False Negative (Missed Match)"
            else:
                fp += 1
                outcome = f"Incorrect (Suggested {suggested_inv} instead of {expected_inv})"

        detailed_results.append({
            "payment_id": pid,
            "expected_invoice": expected_inv,
            "suggested_invoice": suggested_inv,
            "confidence_score": f"{suggested_score}%",
            "confidence_level": suggested_conf,
            "status": suggested_status,
            "match_type": match_type,
            "outcome": outcome,
            "is_correct": is_match
        })

    total_eval = len(df_truth)
    total_correct = tp + correct_unmatched
    precision = (tp / (tp + fp)) * 100 if (tp + fp) > 0 else 0.0
    recall = (tp / (tp + fn)) * 100 if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (total_correct / total_eval) * 100 if total_eval > 0 else 0.0

    stats = get_statistics()
    unmatched_inv = get_unmatched_invoices()
    unallocated_pay = get_unallocated_payments()

    summary = {
        "total_ground_truth_records": total_eval,
        "correct_predictions": total_correct,
        "precision": round(precision, 2),
        "recall": round(recall, 2),
        "f1_score": round(f1, 2),
        "accuracy": round(accuracy, 2),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "correct_unmatched": correct_unmatched,
        "ambiguous_flagged": ambiguous_flagged,
        "unresolved_invoices_count": len(unmatched_inv),
        "unallocated_payments_count": len(unallocated_pay),
        "import_errors_caught": len(inv_errors) + len(pay_errors),
        "total_outstanding_balance": stats["outstanding_balance"],
        "total_unallocated_amount": stats["unallocated_payments"]
    }

    return summary, pd.DataFrame(detailed_results)


if __name__ == "__main__":
    print("\n=======================================================")
    print("RUNNING RECONCILIATION MATCHING BENCHMARK")
    print("=======================================================\n")
    summary, df_details = run_benchmark()

    print(f"Overall Accuracy:  {summary['accuracy']}%")
    print(f"Matching Precision: {summary['precision']}%")
    print(f"Matching Recall:    {summary['recall']}%")
    print(f"F1 Score:           {summary['f1_score']}%")
    print(f"Unresolved Invoices: {summary['unresolved_invoices_count']}")
    print(f"Unallocated Payments: {summary['unallocated_payments_count']}")
    print(f"Validation Errors Caught: {summary['import_errors_caught']}")
    print("\nDetailed Benchmark Results:")
    print(df_details.to_string(index=False))

