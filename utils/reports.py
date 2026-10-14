from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def generate_sales_report_pdf(path, restaurant_name, currency_symbol, period_label, orders):
    """
    orders: list of Order objects (already filtered to the desired date range).
    Writes a PDF to `path` with a summary + itemized order table.
    """
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"{restaurant_name} — Sales Report", styles["Title"]))
    elements.append(Paragraph(period_label, styles["Normal"]))
    elements.append(Spacer(1, 12))

    total_sales = sum(o.total_price for o in orders)
    completed = sum(1 for o in orders if o.status == "Completed")
    summary_data = [
        ["Total Orders", str(len(orders))],
        ["Completed", str(completed)],
        ["Total Sales", f"{currency_symbol}{total_sales:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[150, 150])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 18))

    elements.append(Paragraph("Orders", styles["Heading2"]))
    rows = [["#", "Table", "Total", "Status", "Payment", "Time"]]
    for o in orders:
        rows.append([
            str(o.id), o.table_no or "-", f"{currency_symbol}{o.total_price:,.2f}",
            o.status, o.payment_method, o.created_at.strftime("%Y-%m-%d %H:%M"),
        ])
    order_table = Table(rows, colWidths=[30, 50, 70, 70, 80, 100])
    order_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c9852b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
    ]))
    elements.append(order_table)

    doc.build(elements)
    return path
