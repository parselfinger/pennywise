import json
import os
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import boto3
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pennywise.config import REGION, TXN_TABLE_NAME

# PDF generation imports


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def parse_amount(amount_str):
    """Parse amount string to float, handling various formats."""
    if not amount_str:
        return 0.0

    # Remove currency symbols and commas
    cleaned = (
        str(amount_str)
        .replace("₦", "")
        .replace("$", "")
        .replace(",", "")
        .replace("£", "")
        .replace("€", "")
    )

    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def extract_month_from_date(date_str):
    """Extract month from date string in various formats."""
    if not date_str:
        return None

    # Try different date formats
    date_formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
    ]

    for fmt in date_formats:
        try:
            date_obj = datetime.strptime(str(date_str), fmt)
            return date_obj.strftime("%Y-%m")
        except ValueError:
            continue

    return None


def format_currency(amount):
    """Format amount as currency with proper formatting."""
    return f"₦{abs(amount):,.2f}"


def create_pie_chart(data, title, width=4, height=3):
    """Create a pie chart for the PDF."""

    drawing = Drawing(width * inch, height * inch)
    pie = Pie()
    pie.x = width * inch / 2
    pie.y = height * inch / 2
    pie.width = width * inch * 0.8
    pie.height = height * inch * 0.8

    # Prepare data for pie chart
    labels = []
    values = []
    for label, value in data.items():
        labels.append(label[:15])  # Truncate long labels
        values.append(value)

    pie.data = values
    pie.labels = labels
    pie.slices.strokeWidth = 0.5

    # Add colors - FIX: Capture slice count before iteration to prevent infinite loop
    colors_list = [
        colors.blue,
        colors.green,
        colors.red,
        colors.orange,
        colors.purple,
        colors.brown,
        colors.pink,
        colors.grey,
    ]

    # CRITICAL FIX: Get the number of slices BEFORE iterating to prevent infinite loop
    num_slices = len(pie.slices)
    print(f"🎨 Coloring {num_slices} pie slices...")

    # Use range instead of iterating directly over pie.slices
    for i in range(num_slices):
        if i < len(pie.slices):  # Safety check
            pie.slices[i].fillColor = colors_list[i % len(colors_list)]

    drawing.add(pie)

    # Add legend - FIX: Use list() to prevent iteration issues
    legend = Legend()
    legend.x = width * inch * 0.1
    legend.y = height * inch * 0.1
    legend.alignment = "right"
    legend.fontName = "Helvetica"
    legend.fontSize = 8

    # CRITICAL FIX: Convert data.items() to list to prevent iteration issues
    data_items = list(data.items())
    legend.colorNamePairs = [
        (colors_list[i % len(colors_list)], f"{label}: {format_currency(value)}")
        for i, (label, value) in enumerate(data_items)
    ]
    drawing.add(legend)
    return drawing


def create_bar_chart(data, title, width=6, height=3):
    """Create a bar chart for the PDF."""

    drawing = Drawing(width * inch, height * inch)
    chart = VerticalBarChart()
    chart.x = width * inch * 0.1
    chart.y = height * inch * 0.1
    chart.width = width * inch * 0.8
    chart.height = height * inch * 0.8

    # Prepare data
    labels = []
    values = []
    for label, value in data.items():
        labels.append(label[:12])  # Truncate long labels
        values.append(value)

    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max(values) * 1.2 if values else 100
    chart.valueAxis.valueStep = max(values) / 5 if values else 20

    chart.bars[0].fillColor = colors.blue
    chart.bars[0].strokeColor = colors.black
    chart.bars[0].strokeWidth = 1

    drawing.add(chart)
    return drawing


def generate_monthly_report(table, output_dir="reports", s3_bucket=None, s3_prefix=""):
    """Generate monthly transaction report for the previous month from DynamoDB data."""

    # Initialize S3 client if bucket is provided
    s3_client = None
    if s3_bucket:
        s3_client = boto3.client("s3")

    # Create output directory (for temporary storage)
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # Calculate the previous month (e.g., if we're in September, generate August report)
    current_date = datetime.now()
    if current_date.month == 1:
        # January - previous month is December of previous year
        previous_month = f"{current_date.year - 1}-12"
    else:
        # Other months - previous month is current year, previous month
        previous_month = f"{current_date.year}-{current_date.month - 1:02d}"

    print(f"📅 Generating report for previous month: {previous_month}")

    # Scan all items from DynamoDB
    print("🔍 Scanning DynamoDB for transactions...")
    response = table.scan()
    items = response["Items"]

    # Continue scanning if there are more items (with safety limit)
    scan_count = 1
    max_scans = 100  # Safety limit to prevent infinite loops

    while "LastEvaluatedKey" in response and scan_count < max_scans:
        print(f"🔍 Scan {scan_count + 1}...")
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response["Items"])
        scan_count += 1

    if scan_count >= max_scans:
        print(
            f"⚠️  Warning: Reached maximum scan limit ({max_scans}). Some data may be missing."
        )

    print(f"📊 Found {len(items)} transactions after {scan_count} scans")

    # Filter transactions for the previous month only
    previous_month_transactions = []
    print(f"🔄 Processing transactions for {previous_month}...")
    processed_count = 0

    for item in items:
        processed_count += 1
        if processed_count % 100 == 0:  # Progress indicator every 100 items
            print(f"   Processed {processed_count}/{len(items)} transactions...")

        # Extract date and determine month
        date_str = item.get("date")
        month = extract_month_from_date(date_str)

        if not month:
            print(
                f"⚠️  Warning: Could not parse date for transaction {item.get('description', 'unknown')}"
            )
            continue

        # Only process transactions for the previous month
        if month != previous_month:
            continue

        # Parse amount
        amount_str = item.get("amount")
        amount = parse_amount(amount_str)

        # Determine if it's income or expense based on transactionType
        transaction_type = item.get("transactionType", "").lower()
        category = item.get("category", "Unknown")
        merchant = item.get("merchant", "Unknown")
        description = item.get("description", "")

        if not all([date_str, amount, category, merchant]):
            print(
                f"⚠️  Warning: Skipping transaction with missing essential data: {description}"
            )
            continue

        # Add to previous month transactions
        previous_month_transactions.append(
            {
                "date": date_str,
                "amount": amount,
                "type": transaction_type,
                "category": category,
                "merchant": merchant,
                "description": description,
                "paymentMethod": item.get("paymentMethod", "Unknown"),
            }
        )

    print(
        f"📊 Found {len(previous_month_transactions)} transactions for {previous_month}"
    )

    # Check if we have any transactions for the previous month
    if not previous_month_transactions:
        print(
            f"⚠️  No transactions found for {previous_month}. Report generation skipped."
        )
        return

    # Calculate summary for the previous month
    total_income = 0.0
    total_expenses = 0.0
    categories = defaultdict(float)
    merchants = defaultdict(float)

    for txn in previous_month_transactions:
        if txn["type"] == "credit":
            total_income += txn["amount"]
        else:
            # Treat as expense (debit or any other type)
            total_expenses += abs(txn["amount"])
            categories[txn["category"]] += abs(txn["amount"])
            merchants[txn["merchant"]] += abs(txn["amount"])

    # Calculate net income
    net_income = total_income - total_expenses

    # Sort categories and merchants by amount
    top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:10]
    top_merchants = sorted(merchants.items(), key=lambda x: x[1], reverse=True)[:10]

    # Create report
    report = {
        "month": previous_month,
        "summary": {
            "total_transactions": len(previous_month_transactions),
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_income": net_income,
        },
        "top_categories": [
            {"category": cat, "amount": amt} for cat, amt in top_categories
        ],
        "top_merchants": [
            {"merchant": merch, "amount": amt} for merch, amt in top_merchants
        ],
        "transactions": previous_month_transactions,
    }

    print(f"📅 Generating PDF report for {previous_month}...")

    # Generate PDF report
    pdf_file = output_path / f"transaction_report_{previous_month}.pdf"
    generate_monthly_pdf_report(
        previous_month, report, top_categories, top_merchants, pdf_file
    )

    print(f"✅ Generated PDF report: {pdf_file}")

    # Upload to S3 if bucket is provided
    if s3_client and s3_bucket:
        s3_key = f"{s3_prefix}monthly_reports/{previous_month}/transaction_report_{previous_month}.pdf"
        try:
            s3_client.upload_file(str(pdf_file), s3_bucket, s3_key)
            print(f"📤 Uploaded to S3: s3://{s3_bucket}/{s3_key}")
        except Exception as e:
            print(f"⚠️  Failed to upload to S3: {e}")

    print(f"✅ Monthly report generation completed for {previous_month}!")


def generate_monthly_pdf_report(month, report, top_categories, top_merchants, pdf_file):
    """Generate a professional PDF monthly report."""

    # Create the PDF document
    doc = SimpleDocTemplate(str(pdf_file), pagesize=A4)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        spaceAfter=30,
        alignment=TA_CENTER,
        textColor=colors.darkblue,
    )

    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=16,
        spaceAfter=12,
        spaceBefore=20,
        textColor=colors.darkblue,
    )

    # Build the story (content)
    story = []

    # Title
    try:
        month_date = datetime.strptime(month, "%Y-%m")
        month_display = month_date.strftime("%B %Y")
    except ValueError:
        month_display = month

    story.append(Paragraph("Monthly Transaction Report", title_style))
    story.append(Paragraph(f"{month_display}", title_style))
    story.append(Spacer(1, 20))

    # Financial Summary
    story.append(Paragraph("Financial Summary", heading_style))

    summary_data = [
        ["Metric", "Amount"],
        ["Total Income", format_currency(report["summary"]["total_income"])],
        ["Total Expenses", format_currency(report["summary"]["total_expenses"])],
        ["Net Income", format_currency(report["summary"]["net_income"])],
        ["Total Transactions", str(report["summary"]["total_transactions"])],
    ]

    summary_table = Table(summary_data, colWidths=[2 * inch, 2 * inch])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 10),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 20))

    # Charts
    if top_categories:
        story.append(Paragraph("Spending by Category", heading_style))
        categories_dict = dict(top_categories[:8])
        pie_chart = create_pie_chart(categories_dict, "Spending by Category")
        if pie_chart:
            story.append(pie_chart)
        story.append(Spacer(1, 20))

    if top_merchants:
        story.append(Paragraph("Spending by Merchant", heading_style))
        merchants_dict = dict(top_merchants[:8])
        bar_chart = create_bar_chart(merchants_dict, "Spending by Merchant")
        if bar_chart:
            story.append(bar_chart)
        story.append(Spacer(1, 20))

    # Transaction Details
    story.append(Paragraph("Transaction Details", heading_style))

    # Prepare transaction table data
    transaction_data = [["Date", "Merchant", "Category", "Amount", "Type", "Payment"]]

    # Sort transactions by date
    sorted_transactions = sorted(report["transactions"], key=lambda x: x["date"] or "")

    for txn in sorted_transactions:
        date = txn["date"][:10] if txn["date"] else "Unknown"
        merchant = txn["merchant"][:20] if txn["merchant"] else "Unknown"
        category = txn["category"][:15] if txn["category"] else "Unknown"
        amount = format_currency(txn["amount"])
        txn_type = txn["type"][:10] if txn["type"] else "Unknown"
        payment_method = (
            txn.get("paymentMethod", "Unknown")[:10]
            if txn.get("paymentMethod")
            else "Unknown"
        )

        transaction_data.append(
            [date, merchant, category, amount, txn_type, payment_method]
        )

    # Create transaction table
    transaction_table = Table(
        transaction_data,
        colWidths=[1 * inch, 1.8 * inch, 1.2 * inch, 1 * inch, 0.8 * inch, 0.8 * inch],
    )
    transaction_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),  # Right-align amounts
            ]
        )
    )
    story.append(transaction_table)

    # Footer
    story.append(Spacer(1, 20))
    story.append(
        Paragraph(
            f"Report generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            styles["Normal"],
        )
    )

    # Build the PDF
    doc.build(story)


def generate_overall_pdf_summary(monthly_data, pdf_file):
    """Generate a professional PDF overall summary."""

    # Create the PDF document
    doc = SimpleDocTemplate(str(pdf_file), pagesize=A4)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        spaceAfter=30,
        alignment=TA_CENTER,
        textColor=colors.darkblue,
    )

    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=16,
        spaceAfter=12,
        spaceBefore=20,
        textColor=colors.darkblue,
    )

    # Calculate overall summary
    overall_summary = {
        "total_months": len(monthly_data),
        "total_income": sum(data["total_income"] for data in monthly_data.values()),
        "total_expenses": sum(data["total_expenses"] for data in monthly_data.values()),
        "average_monthly_income": sum(
            data["total_income"] for data in monthly_data.values()
        )
        / len(monthly_data),
        "average_monthly_expenses": sum(
            data["total_expenses"] for data in monthly_data.values()
        )
        / len(monthly_data),
        "monthly_breakdown": {},
    }

    overall_summary["net_income"] = (
        overall_summary["total_income"] - overall_summary["total_expenses"]
    )

    # Monthly breakdown
    for month in sorted(monthly_data.keys()):
        data = monthly_data[month]
        overall_summary["monthly_breakdown"][month] = {
            "income": data["total_income"],
            "expenses": data["total_expenses"],
            "net": data["total_income"] - data["total_expenses"],
        }

    # Build the story
    story = []

    # Title
    story.append(Paragraph("Overall Transaction Summary", title_style))
    story.append(Spacer(1, 20))

    # Period Overview
    if monthly_data:
        first_month = min(monthly_data.keys())
        last_month = max(monthly_data.keys())

        start_date = datetime.strptime(first_month, "%Y-%m").strftime("%B %Y")
        end_date = datetime.strptime(last_month, "%Y-%m").strftime("%B %Y")
        period = f"{start_date} to {end_date}"
    else:
        period = "No data available"

    story.append(Paragraph("Period Overview", heading_style))
    overview_data = [
        ["Period", period],
        ["Total Months", str(overall_summary["total_months"])],
    ]

    overview_table = Table(overview_data, colWidths=[2 * inch, 3 * inch])
    overview_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.lightblue),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )
    story.append(overview_table)
    story.append(Spacer(1, 20))

    # Financial Totals
    story.append(Paragraph("Financial Totals", heading_style))
    totals_data = [
        ["Metric", "Amount"],
        ["Total Income", format_currency(overall_summary["total_income"])],
        ["Total Expenses", format_currency(overall_summary["total_expenses"])],
        ["Net Income", format_currency(overall_summary["net_income"])],
        [
            "Average Monthly Income",
            format_currency(overall_summary["average_monthly_income"]),
        ],
        [
            "Average Monthly Expenses",
            format_currency(overall_summary["average_monthly_expenses"]),
        ],
    ]

    totals_table = Table(totals_data, colWidths=[2.5 * inch, 2 * inch])
    totals_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 10),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Right-align amounts
            ]
        )
    )
    story.append(totals_table)
    story.append(Spacer(1, 20))

    # Monthly Breakdown
    story.append(Paragraph("Monthly Breakdown", heading_style))

    breakdown_data = [["Month", "Income", "Expenses", "Net", "Status"]]

    for month in sorted(overall_summary["monthly_breakdown"].keys()):
        breakdown = overall_summary["monthly_breakdown"][month]
        try:
            month_display = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
        except ValueError:
            month_display = month

        income = format_currency(breakdown["income"])
        expenses = format_currency(breakdown["expenses"])
        net = format_currency(breakdown["net"])

        # Status indicator
        if breakdown["net"] > 0:
            status = "Profit"
        elif breakdown["net"] < 0:
            status = "Loss"
        else:
            status = "Break-even"

        breakdown_data.append([month_display, income, expenses, net, status])

    breakdown_table = Table(
        breakdown_data,
        colWidths=[1.5 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch, 1 * inch],
    )
    breakdown_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("ALIGN", (1, 1), (3, -1), "RIGHT"),  # Right-align amounts
            ]
        )
    )

    # Add row colors for status
    for i in range(1, len(breakdown_data)):
        if breakdown_data[i][4] == "Profit":
            breakdown_table.setStyle(
                TableStyle([("BACKGROUND", (0, i), (-1, i), colors.lightgreen)])
            )
        elif breakdown_data[i][4] == "Loss":
            breakdown_table.setStyle(
                TableStyle([("BACKGROUND", (0, i), (-1, i), colors.lightcoral)])
            )

    story.append(breakdown_table)

    # Footer
    story.append(Spacer(1, 20))
    story.append(
        Paragraph(
            f"Report generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            styles["Normal"],
        )
    )

    # Build the PDF
    doc.build(story)


def lambda_handler(event, context):
    """AWS Lambda handler for generating monthly reports."""
    try:
        print("🚀 Starting monthly PDF report generation via Lambda...")

        # Initialize DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.Table(TXN_TABLE_NAME)

        # Get S3 bucket from environment variables
        reports_s3_bucket = os.environ.get("REPORTS_S3_BUCKET")

        # Use /tmp directory for Lambda (writable)
        output_dir = "/tmp/reports"

        # Generate reports and upload to S3
        generate_monthly_report(
            table, output_dir, s3_bucket=reports_s3_bucket, s3_prefix=""
        )

        print("✅ Monthly PDF report generation completed!")

        return {"statusCode": 200, "body": "Monthly reports generated successfully"}

    except Exception as e:
        print(f"❌ Error generating monthly reports: {str(e)}")
        return {
            "statusCode": 500,
            "body": f"Error generating monthly reports: {str(e)}",
        }
