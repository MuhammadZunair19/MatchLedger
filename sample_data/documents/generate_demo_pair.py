"""Generate the stable MatchLedger demo PO/invoice pair used for manual testing."""
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[2] / "output" / "pdf"
SUPPLIER = "Noor Cable Supplies (Synthetic)"
BUYER = "Madar Projects Demo Organization"


def money(value: Decimal) -> str:
    return f"{value:.2f}"


def create_document(filename: str, title: str, metadata: list[tuple[str, str]], unit_price: Decimal) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    quantity = Decimal("100")
    total = quantity * unit_price
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], textColor=colors.HexColor("#087b72"),
                                 fontName="Helvetica-Bold", fontSize=25, leading=30, spaceAfter=16)
    note_style = ParagraphStyle("note", parent=styles["Normal"], textColor=colors.HexColor("#667b86"),
                                fontSize=8.5, leading=12)
    right_style = ParagraphStyle("right", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=10, leading=15)
    document = SimpleDocTemplate(str(ROOT / filename), pagesize=A4, rightMargin=24 * mm, leftMargin=24 * mm,
                                 topMargin=18 * mm, bottomMargin=18 * mm,
                                 title=title, author="MatchLedger synthetic test data")
    story = [Paragraph("MATCHLEDGER / SYNTHETIC TEST DATA", note_style), Spacer(1, 5 * mm),
             Paragraph(title, title_style)]
    meta_rows = [[Paragraph(f"<b>{label}</b>", styles["Normal"]), Paragraph(value, styles["Normal"])]
                 for label, value in metadata]
    meta = Table(meta_rows, colWidths=[43 * mm, 115 * mm], hAlign="LEFT")
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                              ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#17384a"))]))
    story.extend([meta, Spacer(1, 11 * mm)])
    rows = [["SKU", "Description", "Quantity", "Unit", "Unit price", "Amount"],
            ["CBL-100", "Electrical Cable Rolls", "100", "roll", money(unit_price), money(total)]]
    table = Table(rows, colWidths=[22 * mm, 54 * mm, 25 * mm, 19 * mm, 28 * mm, 28 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e3f0ed")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#17384a")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("LEADING", (0, 0), (-1, -1), 12),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#b8c9ce")),
    ]))
    totals = Table([[Paragraph("Subtotal", right_style), Paragraph(money(total), right_style)],
                    [Paragraph("Discount", right_style), Paragraph("0.00", right_style)],
                    [Paragraph("VAT", right_style), Paragraph("0.00", right_style)],
                    [Paragraph("Grand total", right_style), Paragraph(money(total), right_style)]],
                   colWidths=[35 * mm, 30 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#087b72")),
                                ("TOPPADDING", (0, 0), (-1, -1), 4),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([table, Spacer(1, 10 * mm), totals, Spacer(1, 16 * mm),
                  Paragraph("Fictional organizations and values for MatchLedger testing only. All amounts are in SAR and exclude VAT.", note_style),
                  Spacer(1, 2 * mm), Paragraph("Safe to retain in development and staging. Do not use as a legal or accounting document.", note_style)])
    document.build(story)


if __name__ == "__main__":
    create_document("matchledger-demo-purchase-order.pdf", "PURCHASE ORDER", [
        ("Supplier", SUPPLIER), ("Buyer", BUYER), ("PO number", "PO-DEMO-2026-001"),
        ("Order date", "2026-10-09"), ("Expected delivery", "2026-10-15"),
        ("Currency", "SAR"), ("Supplier VAT", "300000000000003"),
    ], Decimal("50.00"))
    create_document("matchledger-demo-supplier-invoice.pdf", "SUPPLIER INVOICE", [
        ("Supplier", SUPPLIER), ("Buyer", BUYER), ("Invoice number", "INV-DEMO-2026-001"),
        ("Invoice date", "2026-10-09"), ("Due date", "2026-11-08"),
        ("PO reference", "PO-DEMO-2026-001"), ("Currency", "SAR"),
        ("Supplier VAT", "300000000000003"),
    ], Decimal("55.00"))
