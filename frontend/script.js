
// =====================================
// SMART INVOICE RECONCILIATION SYSTEM
// JavaScript Functionality
// =====================================

// Sample data
let invoices = [
    {
        id: "INV-101",
        customer: "Rahul Traders",
        amount: 25000,
        paid: 0
    },
    {
        id: "INV-102",
        customer: "Sharma Enterprises",
        amount: 40000,
        paid: 0
    },
    {
        id: "INV-103",
        customer: "ABC Solutions",
        amount: 15000,
        paid: 0
    }
];

let payments = [
    {
        id: "TXN-501",
        customer: "Rahul Traders",
        amount: 25000,
        allocated: false
    },
    {
        id: "TXN-502",
        customer: "Sharma Enterprises",
        amount: 20000,
        allocated: false
    }
];

// =====================================
// CSV FILE UPLOAD
// =====================================

function uploadFiles() {

    const invoiceFile =
        document.getElementById("invoiceFile").files[0];

    const paymentFile =
        document.getElementById("paymentFile").files[0];

    if (!invoiceFile || !paymentFile) {
        alert("Please upload both Invoice and Payment CSV files.");
        return;
    }

    if (!invoiceFile.name.endsWith(".csv") ||
        !paymentFile.name.endsWith(".csv")) {
        alert("Only CSV files are allowed.");
        return;
    }

    document.getElementById("uploadMessage").innerText =
        "CSV files selected successfully! Backend processing is required.";

    console.log("Invoice File:", invoiceFile.name);
    console.log("Payment File:", paymentFile.name);
}

// =====================================
// MATCH CONFIRMATION
// =====================================

function confirmMatch(button) {

    const row = button.closest("tr");

    const invoiceId = row.cells[0].innerText.trim();
    const paymentId = row.cells[1].innerText.trim();

    const invoice = invoices.find(i => i.id === invoiceId);
    const payment = payments.find(p => p.id === paymentId);

    if (!invoice || !payment) {
        alert("Invoice or payment record not found.");
        return;
    }

    if (payment.allocated) {
        alert("This payment has already been allocated!");
        return;
    }

    if (payment.amount > invoice.amount - invoice.paid) {
        alert("Payment exceeds the outstanding invoice balance. Review required.");
        return;
    }

    if (!confirm("Are you sure you want to confirm this match?")) {
        return;
    }

    invoice.paid += payment.amount;
    payment.allocated = true;

    row.cells[4].innerHTML =
        '<span class="status paid">Confirmed</span>';

    updateDashboard();

    alert("Payment successfully allocated!");
}

// =====================================
// REJECT MATCH
// =====================================

function rejectMatch(button) {

    const row = button.closest("tr");

    if (!confirm("Do you want to reject this match?")) {
        return;
    }

    row.cells[4].innerHTML =
        '<span class="status review">Rejected</span>';

    alert("Match rejected successfully.");
}

// =====================================
// UPDATE DASHBOARD
// =====================================

function updateDashboard() {

    const totalOutstanding = invoices.reduce(
        (sum, invoice) =>
            sum + invoice.amount - invoice.paid,
        0
    );

    const totalPayments = payments.reduce(
        (sum, payment) => sum + payment.amount,
        0
    );

    const allocatedPayments = payments.reduce(
        (sum, payment) =>
            sum + (payment.allocated ? payment.amount : 0),
        0
    );

    console.log("Total Outstanding:", totalOutstanding);
    console.log("Total Payments:", totalPayments);
    console.log("Allocated Payments:", allocatedPayments);

    document.getElementById("totalInvoices").innerText =
        invoices.length;

    const cards = document.querySelectorAll(".card h1");

    if (cards.length >= 3) {
        cards[1].innerText = "₹" + totalPayments.toLocaleString("en-IN");
        cards[2].innerText = "₹" + totalOutstanding.toLocaleString("en-IN");
    }
}

// =====================================
// GENERATE RECONCILIATION REPORT
// =====================================

function generateReport() {

    let report = "Invoice Reconciliation Report\n\n";

    invoices.forEach(invoice => {

        const outstanding = invoice.amount - invoice.paid;

        report +=
            "Invoice: " + invoice.id +
            "\nCustomer: " + invoice.customer +
            "\nAmount: ₹" + invoice.amount +
            "\nPaid: ₹" + invoice.paid +
            "\nOutstanding: ₹" + outstanding +
            "\n---------------------------\n";
    });

    const blob = new Blob([report], {
        type: "text/plain"
    });

    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");

    link.href = url;
    link.download = "reconciliation-report.txt";

    link.click();

    URL.revokeObjectURL(url);
}

// =====================================
// INITIALIZE DASHBOARD
// =====================================

document.addEventListener("DOMContentLoaded", function () {
    updateDashboard();
});
