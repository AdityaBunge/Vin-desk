"""Print-ready GST tax invoice PDF (ReportLab), laid out like a standard Indian dealer invoice:
centre header, party block, itemised table with HSN/SAC, CGST/SGST and round-off rows,
amount in words, HSN-wise tax summary, PAN, declaration and signatory.

A TrueType font with the rupee sign is used when one is installed (Arial on Windows, DejaVu or
Liberation on Linux); otherwise the built-in Helvetica is used and amounts are prefixed "INR".
"""
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.utils import ZERO, format_inr, gst_state
from app.models import Invoice
from app.models.enums import InvoiceStatus, LineType
from app.services.billing import hsn_summary
from app.services.settings import DEFAULTS as settings_defaults

LINE = colors.black
_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf", "C:/Windows/Fonts/arialbi.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf"),
]
_fonts: tuple[str, str, str, str, str] | None = None


def _load_fonts() -> tuple[str, str, str, str, str]:
    """(regular, bold, italic, bold-italic, rupee prefix)."""
    global _fonts
    if _fonts is None:
        _fonts = ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique", "INR")
        for files in _FONT_CANDIDATES:
            # Regular and bold are required; servers often lack the italic files (e.g. Debian's
            # fonts-dejavu-core), so italics fall back to the upright faces.
            if not (Path(files[0]).exists() and Path(files[1]).exists()):
                continue
            files = (files[0], files[1],
                     files[2] if Path(files[2]).exists() else files[0],
                     files[3] if Path(files[3]).exists() else files[1])
            try:
                names = ("Inv", "Inv-Bold", "Inv-Italic", "Inv-BoldItalic")
                for name, path in zip(names, files):
                    pdfmetrics.registerFont(TTFont(name, path))
                pdfmetrics.registerFontFamily("Inv", normal="Inv", bold="Inv-Bold", italic="Inv-Italic", boldItalic="Inv-BoldItalic")
                rupee = "\u20b9" if 0x20B9 in TTFont("probe", files[0]).face.charToGlyph else "INR"
                _fonts = (*names, rupee)
                break
            except Exception:  # noqa: BLE001 - a broken font file must never block invoicing
                continue
    return _fonts


def _qty(value) -> str:
    text = f"{Decimal(value):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _rate(value) -> str:
    return f"{_qty(value)}%"


def render_invoice_pdf(inv: Invoice) -> bytes:
    regular, bold, italic, bold_italic, rupee = _load_fonts()
    base = ParagraphStyle("base", fontName=regular, fontSize=8.5, leading=11)
    centre_style = ParagraphStyle("centre", parent=base, alignment=TA_CENTER, leading=10.5)
    right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT)
    cell = ParagraphStyle("cell", parent=base, fontName=bold, fontSize=8.5, leading=10)
    small = ParagraphStyle("small", parent=base, fontSize=7.5, leading=9.5)
    p = lambda text, style=base: Paragraph(text, style)  # noqa: E731
    e = lambda value: escape(str(value or ""))  # noqa: E731

    centre = inv.centre or {}
    status = inv.status
    number = inv.invoice_number or "DRAFT"
    date = inv.finalised_at or inv.created_at
    split = bool(centre.get("gst_split_intra_state", True))
    lines = sorted(inv.lines, key=lambda l: (l.line_type == LineType.LABOUR, l.sort_order))
    any_discount = any(l.discount_amount > 0 for l in lines)

    def watermark(canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setFont(regular, 7)
            canvas.drawRightString(198 * mm, 8 * mm, f"{number} - page {doc.page}")
        if status != InvoiceStatus.FINALISED:
            canvas.setFont(bold, 60)
            canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.12))
            canvas.translate(105 * mm, 150 * mm)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "DRAFT" if status == InvoiceStatus.DRAFT else "CANCELLED")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
        title=f"Invoice {number}", author=centre.get("name", ""),
    )
    width = doc.width
    story: list = []

    # --- Invoice number / date -------------------------------------------------------------
    top = Table(
        [[p(f"Invoice No. <b>{e(number)}</b>"), p(f"Dated <b>{date:%d-%b-%y}</b>", right)],
         [p(f"Ref. No. {e(inv.job_number)}"), ""]],
        colWidths=[width / 2, width / 2],
    )
    top.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                             ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [top, Spacer(1, 2 * mm)]

    # --- Centre header -------------------------------------------------------------------------
    header = [f"<font size=10><b>{e(centre.get('name'))}</b></font>"]
    header += [e(line) for line in str(centre.get("address") or "").splitlines() if line.strip()]
    if centre.get("gstin"):
        header.append(f"GSTIN/UIN: {e(centre['gstin'])}")
    state = gst_state(centre.get("gstin")) or (
        (centre.get("state_name"), centre.get("state_code")) if centre.get("state_name") else None
    )
    if state:
        header.append(f"State Name : {e(state[0])}, Code : {e(state[1])}")
    contact = [f"Phone : {e(centre['phone'])}" if centre.get("phone") else "", f"E-Mail : {e(centre['email'])}" if centre.get("email") else ""]
    if any(contact):
        header.append(" &nbsp; ".join(c for c in contact if c))
    if centre.get("other_registration"):
        header.append(e(centre["other_registration"]))
    story += [p("<br/>".join(header), centre_style), Spacer(1, 3 * mm),
              p("<font size=11><b>Tax Invoice</b></font>", centre_style), Spacer(1, 3 * mm)]

    # --- Party ---------------------------------------------------------------------------------
    party = [f"Party : <b>{e(inv.customer_name)}</b>"]
    party += [e(line) for line in str(inv.billing_address or "").splitlines() if line.strip()]
    if inv.customer_gstin:
        party.append(f"GSTIN/UIN &nbsp;&nbsp;: {e(inv.customer_gstin)}")
    party_state = gst_state(inv.customer_gstin) or state
    if party_state:
        party.append(f"State Name &nbsp;: {e(party_state[0])}, Code : {e(party_state[1])}")
    party.append(f"Vehicle &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;: {e(inv.vehicle_registration)} ({e(inv.vehicle_model)})")
    party_table = Table([[p("<br/>".join(party))]], colWidths=[width * 0.62])
    party_table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    party_table.hAlign = "CENTER"
    story += [party_table, Spacer(1, 2 * mm)]

    # --- Items ---------------------------------------------------------------------------------
    head = ["Sl\nNo.", "Description of\nGoods and Services", "HSN/SAC", "Quantity", "Rate", "per"]
    widths = [9 * mm, None, 20 * mm, 19 * mm, 21 * mm, 11 * mm]
    if any_discount:
        head.append("Disc.")
        widths.append(17 * mm)
    head.append("Amount")
    widths.append(27 * mm)
    widths[1] = width - sum(w for w in widths if w)
    amount_col = len(head) - 1
    rows: list[list] = [head]
    for index, line in enumerate(lines, start=1):
        labour = line.line_type == LineType.LABOUR
        gross = line.quantity * line.unit_price
        row = [
            str(index), p(e(line.description).upper(), cell), line.hsn_code or "",
            "" if labour else f"{_qty(line.quantity)} {line.unit}".strip(),
            "" if labour else format_inr(line.unit_price), "" if labour else line.unit,
        ]
        if any_discount:
            row.append(format_inr(line.discount_amount) if line.discount_amount > 0 else "")
        row.append(format_inr(gross - line.discount_amount))
        rows.append(row)
    item_count = len(rows) - 1

    def summary_row(label: str, amount: str, rule: bool = False) -> None:
        row = ["", p(f"<b><i>{e(label)}</i></b>", right) if label else ""] + [""] * (len(head) - 3) + [amount]
        rows.append(row)
        if rule:
            rules.append(len(rows) - 1)

    rules: list[int] = []
    summary_row("", format_inr(inv.taxable_total), rule=True)
    tax_rows = hsn_summary(inv)
    if split:
        cgst = sum((r.get("cgst", ZERO) for r in tax_rows), ZERO)
        summary_row("CGST", format_inr(cgst))
        summary_row("SGST", format_inr(inv.tax_total - cgst))
    elif inv.tax_total:
        summary_row("IGST", format_inr(inv.tax_total))
    if inv.round_off:
        summary_row("Round Off", ("" if inv.round_off > 0 else "(-)") + format_inr(abs(inv.round_off)))
    # Blank space so the table reaches down the page like a printed invoice.
    filler_height = max(4 * mm, 95 * mm - (len(rows) - 1) * 5.2 * mm)
    rows.append([""] * len(head))
    filler = len(rows) - 1
    rows.append(["", p("<b>Total</b>", right)] + [""] * (len(head) - 3) + [p(f"<b>{rupee} {format_inr(inv.total)}</b>", right)])
    heights = [None] * len(rows)
    heights[filler] = filler_height

    items = Table(rows, colWidths=widths, rowHeights=heights, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), regular), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (3, 1), (3, item_count), bold), ("FONTNAME", (amount_col, 1), (amount_col, item_count), bold),
        ("FONTSIZE", (0, 0), (-1, 0), 8), ("ALIGN", (0, 0), (-1, 0), "CENTER"), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("VALIGN", (0, 1), (-1, -1), "TOP"), ("ALIGN", (3, 1), (-1, -1), "RIGHT"), ("ALIGN", (5, 1), (5, -1), "LEFT"),
        ("TOPPADDING", (0, 1), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 1), (-1, -1), 1.5),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE), ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, LINE),
    ]
    for col in range(len(head) - 1):
        style.append(("LINEAFTER", (col, 0), (col, -1), 0.4, LINE))
    for r in rules:
        style.append(("LINEABOVE", (amount_col, r), (amount_col, r), 0.4, LINE))
    items.setStyle(TableStyle(style))
    story.append(items)

    # --- Amount in words ---------------------------------------------------------------------
    words = Table(
        [[p("Amount Chargeable (in words)", small), p("<i>E. &amp; O.E</i>", ParagraphStyle("eoe", parent=small, alignment=TA_RIGHT))],
         [p(f"<b>{e(inv.total_in_words)}</b>", ParagraphStyle("w", parent=base, fontSize=9.5, leading=12)), ""]],
        colWidths=[width * 0.8, width * 0.2],
    )
    words.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("SPAN", (0, 1), (1, 1))]))
    story += [words, Spacer(1, 1.5 * mm)]

    # --- HSN/SAC tax summary -----------------------------------------------------------------
    if split:
        hsn_rows = [["HSN/SAC", "Taxable\nValue", "CGST", "", "SGST/UTGST", "", "Total\nTax Amount"],
                    ["", "", "Rate", "Amount", "Rate", "Amount", ""]]
        for r in tax_rows:
            hsn_rows.append([r["hsn_code"], format_inr(r["taxable"]), _rate(r["cgst_rate"]), format_inr(r["cgst"]),
                             _rate(r["sgst_rate"]), format_inr(r["sgst"]), format_inr(r["tax"])])
        cgst_total = sum((r["cgst"] for r in tax_rows), ZERO)
        hsn_rows.append(["Total", format_inr(inv.taxable_total), "", format_inr(cgst_total), "",
                         format_inr(inv.tax_total - cgst_total), format_inr(inv.tax_total)])
        hsn_widths = [None, 26 * mm, 13 * mm, 22 * mm, 13 * mm, 22 * mm, 26 * mm]
        spans = [("SPAN", (2, 0), (3, 0)), ("SPAN", (4, 0), (5, 0)), ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (1, 1)), ("SPAN", (6, 0), (6, 1))]
    else:
        hsn_rows = [["HSN/SAC", "Taxable\nValue", "Integrated Tax", "", "Total\nTax Amount"], ["", "", "Rate", "Amount", ""]]
        for r in tax_rows:
            hsn_rows.append([r["hsn_code"], format_inr(r["taxable"]), _rate(r["rate"]), format_inr(r["tax"]), format_inr(r["tax"])])
        hsn_rows.append(["Total", format_inr(inv.taxable_total), "", format_inr(inv.tax_total), format_inr(inv.tax_total)])
        hsn_widths = [None, 30 * mm, 15 * mm, 26 * mm, 30 * mm]
        spans = [("SPAN", (2, 0), (3, 0)), ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (1, 1)), ("SPAN", (4, 0), (4, 1))]
    hsn_widths[0] = width - sum(w for w in hsn_widths if w)
    hsn = Table(hsn_rows, colWidths=hsn_widths)
    hsn.setStyle(TableStyle(spans + [
        ("FONTNAME", (0, 0), (-1, -1), regular), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("LEADING", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, 1), "CENTER"), ("VALIGN", (0, 0), (-1, 1), "MIDDLE"), ("ALIGN", (1, 2), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), bold), ("ALIGN", (0, -1), (0, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
    ]))
    story += [hsn, Spacer(1, 1.5 * mm)]

    tail = [p(f"Tax Amount (in words) : &nbsp;<b>{e(inv.tax_in_words)}</b>")]
    if centre.get("pan"):
        tail.append(p(f"Company's PAN &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;: &nbsp;<b>{e(centre['pan'])}</b>"))
    tail.append(Spacer(1, 3 * mm))

    # --- Declaration and signatory -----------------------------------------------------------
    declaration = centre.get("declaration") or settings_defaults["invoice_declaration"]
    left = [p("<u>Declaration</u>", small), p(e(declaration), small)]
    if inv.terms:
        left += [Spacer(1, 1.5 * mm), p(f"<b>Terms:</b> {e(inv.terms)}", small)]
    if inv.notes:
        left += [Spacer(1, 1 * mm), p(f"<b>Notes:</b> {e(inv.notes)}", small)]
    sign = [p(f"<b>for {e(centre.get('name'))}</b>", right), Spacer(1, 12 * mm), p("Authorised Signatory", ParagraphStyle("sig", parent=small, alignment=TA_RIGHT))]
    footer = Table([[left, sign]], colWidths=[width * 0.55, width * 0.45])
    footer.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    tail += [footer, Spacer(1, 4 * mm), p("<u>This is a Computer Generated Invoice</u>", ParagraphStyle("cg", parent=small, alignment=TA_CENTER))]
    story.append(KeepTogether(tail))

    doc.build(story, onFirstPage=watermark, onLaterPages=watermark)
    return buffer.getvalue()
