"""GST tax-invoice details: HSN/SAC codes, units, customer GSTIN, HSN summary, round-off, words."""
from sqlalchemy import update

from app.core.database import SessionLocal
from app.core.utils import financial_year_suffix, gst_state, rupees_in_words
from app.models import LabourOperation, Part
from tests import flow


def test_amount_in_words_uses_indian_numbering():
    assert rupees_in_words(46447) == "INR Forty Six Thousand Four Hundred Forty Seven Only"
    assert rupees_in_words(7124) == "INR Seven Thousand One Hundred Twenty Four Only"
    assert rupees_in_words("12345678.50") == "INR One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight and Fifty paise Only"
    assert gst_state("27AAALM4691H1ZS") == ("Maharashtra", "27") and gst_state("") is None


def test_invoice_carries_hsn_codes_units_and_customer_gstin(w):
    with SessionLocal() as db:
        db.execute(update(Part).where(Part.sku == "OIL").values(hsn_code="27101980", unit="Nos"))
        db.execute(update(LabourOperation).where(LabourOperation.code == "LAB-GS").values(sac_code="998512"))
        db.commit()
    job = flow.to_billing(w)
    customer_url = f"/customers/{job['customer']['id']}"
    bad = w.call("manager", "PATCH", customer_url, json={"gstin": "NOT-A-GSTIN"})
    assert bad.status_code == 422
    assert w.ok("manager", "PATCH", customer_url, json={"gstin": "27aaalm4691h1zs"})["gstin"] == "27AAALM4691H1ZS"

    inv = flow.finalise(w, job["id"])
    assert inv["customer_gstin"] == "27AAALM4691H1ZS"
    by_type = {l["line_type"]: l for l in inv["lines"]}
    assert (by_type["PART"]["hsn_code"], by_type["PART"]["unit"]) == ("27101980", "Nos")
    assert by_type["LABOUR"]["hsn_code"] == "998512"  # SAC from the labour operation

    summary = {r["hsn_code"]: r for r in inv["hsn_summary"]}
    assert set(summary) == {"27101980", "998512"}
    assert summary["27101980"]["cgst_rate"] == "9.00" and summary["27101980"]["sgst_rate"] == "9.00"
    taxable = sum(float(r["taxable"]) for r in inv["hsn_summary"])
    assert round(taxable, 2) == float(inv["taxable_total"])
    assert inv["total_in_words"].startswith("INR ") and inv["total_in_words"].endswith(" Only")
    assert float(inv["total"]) == round(float(inv["total"]))  # whole rupees

    pdf = w.call("manager", "GET", f"/invoices/{inv['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_blank_labour_sac_falls_back_to_the_centre_default(w):
    w.ok("admin", "PUT", "/settings", json={"default_labour_sac": "998714", "centre_pan": "aavfb6252c"})
    assert w.ok("admin", "GET", "/settings")["values"]["centre_pan"] == "AAVFB6252C"
    inv = flow.finalise(w, flow.to_billing(w)["id"])
    labour = next(l for l in inv["lines"] if l["line_type"] == "LABOUR")
    assert labour["hsn_code"] == "998714"
    assert inv["centre"]["pan"] == "AAVFB6252C"
    assert w.call("admin", "PUT", "/settings", json={"centre_pan": "BAD"}).status_code == 422


def test_financial_year_suffix_changes_on_1_april():
    from datetime import date

    assert financial_year_suffix(date(2025, 12, 21)) == "F.Y:25-26 - (from 1-Apr-25)"
    assert financial_year_suffix(date(2026, 3, 31)) == "F.Y:25-26 - (from 1-Apr-25)"
    assert financial_year_suffix(date(2026, 4, 1)) == "F.Y:26-27 - (from 1-Apr-26)"


def test_business_name_carries_the_financial_year_of_the_invoice(w):
    from datetime import date

    from app.services import settings as settings_service

    w.ok("admin", "PUT", "/settings", json={"centre_name": "Positive Sales", "centre_name_with_fy": True})
    with SessionLocal() as db:
        assert settings_service.centre_snapshot(db, date(2027, 2, 1))["name"] == "Positive Sales F.Y:26-27 - (from 1-Apr-26)"
    inv = flow.finalise(w, flow.to_billing(w)["id"])
    assert inv["centre"]["name"].startswith("Positive Sales F.Y:") and "(from 1-Apr-" in inv["centre"]["name"]
    # Switched off, the name prints exactly as entered.
    w.ok("admin", "PUT", "/settings", json={"centre_name_with_fy": False})
    with SessionLocal() as db:
        assert settings_service.centre_snapshot(db)["name"] == "Positive Sales"
