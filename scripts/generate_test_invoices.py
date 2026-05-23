"""Generate three realistic Indian GST invoice PDFs for end-to-end pipeline testing.

Variety 1: Intra-state — Maharashtra seller to Maharashtra buyer (CGST + SGST)
Variety 2: Inter-state — Karnataka seller to Tamil Nadu buyer (IGST)
Variety 3: Service invoice — Delhi consultant to Mumbai client (inter-state, IGST, SAC codes)
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
)


OUTPUT_DIR = Path("datasets/source_docs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="Title2", parent=s["Title"], fontSize=18, alignment=1, spaceAfter=6))
    s.add(ParagraphStyle(name="Center", parent=s["Normal"], alignment=1))
    s.add(ParagraphStyle(name="SmallBold", parent=s["Normal"], fontSize=9, fontName="Helvetica-Bold"))
    s.add(ParagraphStyle(name="Small", parent=s["Normal"], fontSize=9))
    return s


def _section_header(text, styles):
    return Paragraph(f"<b>{text}</b>", styles["SmallBold"])


def _build_party_table(label, party_lines, styles):
    inner = [[Paragraph(f"<b>{label}</b>", styles["SmallBold"])]] + [
        [Paragraph(line, styles["Small"])] for line in party_lines
    ]
    return Table(inner, colWidths=[85 * mm], style=TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))


def _build_line_items_table(items, columns):
    """items: list of dicts. columns: list of (key, header, width_mm)."""
    headers = [c[1] for c in columns]
    widths = [c[2] * mm for c in columns]
    data = [headers]
    for item in items:
        data.append([str(item.get(c[0], "")) for c in columns])
    return Table(data, colWidths=widths, style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))


def _build_totals_table(rows, label_width=120, value_width=40):
    data = [[r[0], r[1]] for r in rows]
    return Table(data, colWidths=[label_width * mm, value_width * mm], style=TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))


# ─────────────────────────────────────────────────────────
# Variety 1: Intra-state (Maharashtra → Maharashtra) CGST+SGST
# ─────────────────────────────────────────────────────────
def generate_invoice_1():
    out_path = OUTPUT_DIR / "invoice_1_intrastate_maharashtra.pdf"
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = _styles()
    story = []

    story.append(Paragraph("TAX INVOICE", styles["Title2"]))
    story.append(Paragraph("Original for Recipient", styles["Center"]))
    story.append(Spacer(1, 8))

    meta = Table([
        ["Invoice No:", "INV/2024/0042", "Invoice Date:", "15-04-2024"],
        ["PO Number:", "PO-MH-2024-118", "Due Date:", "30-04-2024"],
        ["Place of Supply:", "Maharashtra (27)", "Reverse Charge:", "No"],
    ], colWidths=[40 * mm, 55 * mm, 35 * mm, 50 * mm], style=TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
    ]))
    story.append(meta)
    story.append(Spacer(1, 10))

    seller_lines = [
        "Mehta Electronics Pvt Ltd",
        "Shop No. 14, MG Road",
        "Andheri East, Mumbai - 400069",
        "Maharashtra, India",
        "GSTIN: 27AABCM1234D1Z5",
        "PAN: AABCM1234D",
        "Phone: +91-22-2683-4521",
    ]
    buyer_lines = [
        "Rajesh Trading Co.",
        "Plot 7, Industrial Estate",
        "Bhandup West, Mumbai - 400078",
        "Maharashtra, India",
        "GSTIN: 27AAFCR9876E1Z7",
        "PAN: AAFCR9876E",
        "Phone: +91-22-2596-1240",
    ]

    parties = Table([
        [_build_party_table("Seller / Supplier", seller_lines, styles),
         _build_party_table("Buyer / Recipient", buyer_lines, styles)],
    ], colWidths=[90 * mm, 90 * mm])
    story.append(parties)
    story.append(Spacer(1, 10))

    items = [
        {
            "sno": "1", "desc": "Samsung 55-inch Smart LED TV",
            "hsn": "85287200", "qty": "2", "uom": "NOS", "rate": "45000.00",
            "taxable": "90000.00",
            "cgst_rate": "9%", "cgst_amt": "8100.00",
            "sgst_rate": "9%", "sgst_amt": "8100.00",
            "total": "106200.00",
        },
        {
            "sno": "2", "desc": "Sony Soundbar HT-S350",
            "hsn": "85182900", "qty": "2", "uom": "NOS", "rate": "12500.00",
            "taxable": "25000.00",
            "cgst_rate": "9%", "cgst_amt": "2250.00",
            "sgst_rate": "9%", "sgst_amt": "2250.00",
            "total": "29500.00",
        },
        {
            "sno": "3", "desc": "HDMI Cable 2m (Premium)",
            "hsn": "85444299", "qty": "10", "uom": "NOS", "rate": "350.00",
            "taxable": "3500.00",
            "cgst_rate": "9%", "cgst_amt": "315.00",
            "sgst_rate": "9%", "sgst_amt": "315.00",
            "total": "4130.00",
        },
    ]
    columns = [
        ("sno", "#", 8),
        ("desc", "Description", 55),
        ("hsn", "HSN", 18),
        ("qty", "Qty", 10),
        ("uom", "UOM", 12),
        ("rate", "Rate", 18),
        ("taxable", "Taxable", 22),
        ("cgst_amt", "CGST 9%", 18),
        ("sgst_amt", "SGST 9%", 18),
        ("total", "Total", 20),
    ]
    story.append(_build_line_items_table(items, columns))
    story.append(Spacer(1, 8))

    totals = [
        ["Subtotal (Taxable Value):", "Rs. 1,18,500.00"],
        ["CGST @ 9%:", "Rs. 10,665.00"],
        ["SGST @ 9%:", "Rs. 10,665.00"],
        ["Total Tax:", "Rs. 21,330.00"],
        ["Grand Total:", "Rs. 1,39,830.00"],
    ]
    story.append(_build_totals_table(totals))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Amount in Words:</b> One Lakh Thirty Nine Thousand Eight Hundred Thirty Rupees Only", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Bank Details:</b> Mehta Electronics Pvt Ltd | HDFC Bank | A/c: 50100123456789 | IFSC: HDFC0000123", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Payment Terms:</b> Net 15 days from invoice date. Late payments subject to 18% interest p.a.", styles["Small"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<i>Declaration:</i> Certified that the particulars given above are true and correct.", styles["Small"]))
    story.append(Spacer(1, 16))
    story.append(Paragraph("For Mehta Electronics Pvt Ltd", styles["SmallBold"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Authorized Signatory", styles["Small"]))

    doc.build(story)
    return out_path


# ─────────────────────────────────────────────────────────
# Variety 2: Inter-state (Karnataka → Tamil Nadu) IGST
# ─────────────────────────────────────────────────────────
def generate_invoice_2():
    out_path = OUTPUT_DIR / "invoice_2_interstate_karnataka_tamilnadu.pdf"
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = _styles()
    story = []

    story.append(Paragraph("TAX INVOICE", styles["Title2"]))
    story.append(Paragraph("Original for Recipient", styles["Center"]))
    story.append(Spacer(1, 8))

    meta = Table([
        ["Invoice No:", "BLR-TN-2024-887", "Invoice Date:", "22-05-2024"],
        ["PO Number:", "PO-CHN-998", "Due Date:", "21-06-2024"],
        ["Place of Supply:", "Tamil Nadu (33)", "Reverse Charge:", "No"],
    ], colWidths=[40 * mm, 55 * mm, 35 * mm, 50 * mm], style=TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
    ]))
    story.append(meta)
    story.append(Spacer(1, 10))

    seller_lines = [
        "Bangalore Components Ltd",
        "Plot 45, Electronic City Phase 2",
        "Bangalore - 560100",
        "Karnataka, India",
        "GSTIN: 29AABCB5678P1Z2",
        "PAN: AABCB5678P",
        "Phone: +91-80-2841-6700",
    ]
    buyer_lines = [
        "Chennai Tech Solutions",
        "No. 12, Anna Salai",
        "Teynampet, Chennai - 600018",
        "Tamil Nadu, India",
        "GSTIN: 33AAACG4321Q1Z9",
        "PAN: AAACG4321Q",
        "Phone: +91-44-2433-9800",
    ]

    parties = Table([
        [_build_party_table("Seller / Supplier", seller_lines, styles),
         _build_party_table("Buyer / Recipient", buyer_lines, styles)],
    ], colWidths=[90 * mm, 90 * mm])
    story.append(parties)
    story.append(Spacer(1, 10))

    items = [
        {
            "sno": "1", "desc": "Intel Core i7-13700K Processor",
            "hsn": "85423100", "qty": "5", "uom": "NOS", "rate": "32000.00",
            "taxable": "160000.00",
            "igst_rate": "18%", "igst_amt": "28800.00",
            "total": "188800.00",
        },
        {
            "sno": "2", "desc": "Corsair DDR5 32GB RAM Kit",
            "hsn": "84733092", "qty": "10", "uom": "NOS", "rate": "9500.00",
            "taxable": "95000.00",
            "igst_rate": "18%", "igst_amt": "17100.00",
            "total": "112100.00",
        },
        {
            "sno": "3", "desc": "Samsung 980 PRO 2TB NVMe SSD",
            "hsn": "84717030", "qty": "8", "uom": "NOS", "rate": "14500.00",
            "taxable": "116000.00",
            "igst_rate": "18%", "igst_amt": "20880.00",
            "total": "136880.00",
        },
        {
            "sno": "4", "desc": "ASUS ROG STRIX Z790-E Motherboard",
            "hsn": "84733099", "qty": "5", "uom": "NOS", "rate": "28000.00",
            "taxable": "140000.00",
            "igst_rate": "18%", "igst_amt": "25200.00",
            "total": "165200.00",
        },
    ]
    columns = [
        ("sno", "#", 8),
        ("desc", "Description", 60),
        ("hsn", "HSN", 18),
        ("qty", "Qty", 10),
        ("uom", "UOM", 12),
        ("rate", "Rate", 20),
        ("taxable", "Taxable Value", 28),
        ("igst_amt", "IGST 18%", 22),
        ("total", "Total", 22),
    ]
    story.append(_build_line_items_table(items, columns))
    story.append(Spacer(1, 8))

    totals = [
        ["Subtotal (Taxable Value):", "Rs. 5,11,000.00"],
        ["IGST @ 18%:", "Rs. 91,980.00"],
        ["Total Tax:", "Rs. 91,980.00"],
        ["Grand Total:", "Rs. 6,02,980.00"],
    ]
    story.append(_build_totals_table(totals))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Amount in Words:</b> Six Lakh Two Thousand Nine Hundred Eighty Rupees Only", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Transport Details:</b> Mode: Road | Transporter: VRL Logistics | LR No: VRL-BLR-2024-7788 | Vehicle: KA-01-AB-1234", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>E-Way Bill No:</b> 8812 3456 7890", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Bank Details:</b> Bangalore Components Ltd | ICICI Bank | A/c: 002701234567 | IFSC: ICIC0000027", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Payment Terms:</b> Net 30 days from invoice date.", styles["Small"]))
    story.append(Spacer(1, 16))
    story.append(Paragraph("For Bangalore Components Ltd", styles["SmallBold"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Authorized Signatory", styles["Small"]))

    doc.build(story)
    return out_path


# ─────────────────────────────────────────────────────────
# Variety 3: Service invoice (Delhi → Mumbai) IGST with SAC codes
# ─────────────────────────────────────────────────────────
def generate_invoice_3():
    out_path = OUTPUT_DIR / "invoice_3_service_delhi_mumbai.pdf"
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = _styles()
    story = []

    story.append(Paragraph("TAX INVOICE", styles["Title2"]))
    story.append(Paragraph("Services Invoice — Original for Recipient", styles["Center"]))
    story.append(Spacer(1, 8))

    meta = Table([
        ["Invoice No:", "DEL/SRV/2024/2156", "Invoice Date:", "08-06-2024"],
        ["Project Ref:", "PRJ-FY24-Q2-MUM-09", "Due Date:", "08-07-2024"],
        ["Place of Supply:", "Maharashtra (27)", "Reverse Charge:", "No"],
    ], colWidths=[40 * mm, 55 * mm, 35 * mm, 50 * mm], style=TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
    ]))
    story.append(meta)
    story.append(Spacer(1, 10))

    seller_lines = [
        "Sharma Consulting Services LLP",
        "Office 502, Connaught Place",
        "New Delhi - 110001",
        "Delhi, India",
        "GSTIN: 07AABFS3456J1ZK",
        "PAN: AABFS3456J",
        "Phone: +91-11-4567-8900",
    ]
    buyer_lines = [
        "Mumbai Finance Group Pvt Ltd",
        "21st Floor, World Trade Center",
        "Cuffe Parade, Mumbai - 400005",
        "Maharashtra, India",
        "GSTIN: 27AAACM7890K1Z3",
        "PAN: AAACM7890K",
        "Phone: +91-22-6650-1100",
    ]

    parties = Table([
        [_build_party_table("Service Provider", seller_lines, styles),
         _build_party_table("Service Recipient", buyer_lines, styles)],
    ], colWidths=[90 * mm, 90 * mm])
    story.append(parties)
    story.append(Spacer(1, 10))

    items = [
        {
            "sno": "1",
            "desc": "Management Consulting Services - Q2 FY24",
            "sac": "998311", "qty": "1", "uom": "MONTHS", "rate": "250000.00",
            "taxable": "250000.00",
            "igst_rate": "18%", "igst_amt": "45000.00",
            "total": "295000.00",
        },
        {
            "sno": "2",
            "desc": "Financial Advisory Services - Strategic Review",
            "sac": "998312", "qty": "1", "uom": "PROJECT", "rate": "180000.00",
            "taxable": "180000.00",
            "igst_rate": "18%", "igst_amt": "32400.00",
            "total": "212400.00",
        },
        {
            "sno": "3",
            "desc": "Process Optimization Workshop (3-day)",
            "sac": "999293", "qty": "3", "uom": "DAYS", "rate": "40000.00",
            "taxable": "120000.00",
            "igst_rate": "18%", "igst_amt": "21600.00",
            "total": "141600.00",
        },
    ]
    columns = [
        ("sno", "#", 8),
        ("desc", "Service Description", 65),
        ("sac", "SAC", 18),
        ("qty", "Qty", 10),
        ("uom", "UOM", 15),
        ("rate", "Rate", 22),
        ("taxable", "Taxable Value", 28),
        ("igst_amt", "IGST 18%", 20),
        ("total", "Total", 22),
    ]
    story.append(_build_line_items_table(items, columns))
    story.append(Spacer(1, 8))

    totals = [
        ["Subtotal (Taxable Value):", "Rs. 5,50,000.00"],
        ["IGST @ 18%:", "Rs. 99,000.00"],
        ["Total Tax:", "Rs. 99,000.00"],
        ["Grand Total:", "Rs. 6,49,000.00"],
    ]
    story.append(_build_totals_table(totals))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Amount in Words:</b> Six Lakh Forty Nine Thousand Rupees Only", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Bank Details:</b> Sharma Consulting Services LLP | Axis Bank | A/c: 912010012345678 | IFSC: UTIB0000456", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Payment Terms:</b> Net 30 days. Bank transfer (NEFT/RTGS) preferred.", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<i>Note: Service tax under reverse charge mechanism is not applicable.</i>", styles["Small"]))
    story.append(Spacer(1, 16))
    story.append(Paragraph("For Sharma Consulting Services LLP", styles["SmallBold"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Authorized Signatory", styles["Small"]))

    doc.build(story)
    return out_path


if __name__ == "__main__":
    paths = [generate_invoice_1(), generate_invoice_2(), generate_invoice_3()]
    for p in paths:
        print(f"Generated: {p}")
