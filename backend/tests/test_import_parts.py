"""Importing the parts catalogue and opening stock from the workshop's closing-stock sheet."""
import csv
import io
from decimal import Decimal

from sqlalchemy import select

from app.import_parts import import_parts, parse_sheet
from app.models import InventoryMovement, Part, TaxRate, User
from app.models.enums import MovementType

# The layout of the dealer system's export: title rows, then the header, then numbered rows.
SHEET = """M/S POSITIVE SALES,,,,,,,,,,,,,,,,,,,,,
Part Category,, :    Spares,,,,,,,,,,,,,,,,,,,
Sr.No.,Part Number,Part Description,,BIN ,Category,,Movement ,ABC,,HML,RIS,Closing Qty.,,,Closing Value,,,,,BIN NUMBER ,ACTUAL  QUANTITY
1,A000023020512,THRUST WASHER(PRESSURE DISC)MCED,,NO BIN,00001,,M5,C,,L,S,5,,,753.6,,,,,,
2,a000023525142,OIL  SEAL,,NO BIN,00001,,M4,C,,L,S,19,,,"2,179.48",,,,,B3,12
3,A000040110080,ZERO STOCK PART,,NO BIN,00001,,M5,C,,L,S,0,,,0,,,,,,
4,B008081420280,GAS,GAEKET INTAKE MIDDLE,NO BIN,,,,,,,,,,,,,,,,,
5,,,BOSH PUMP GASKET,,,,,,,,,,,,,,,,,,
6,A000023020512,,THRUST WASHER AGAIN,,,,,,,,,,,,,,,,,A49A,4
7,,,,,,,,,,,,,,,,,,,,,
"""


def rows(text: str = SHEET) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_parse_sheet_reads_counts_costs_and_hand_added_rows():
    result = parse_sheet(rows())
    by_sku = {p.sku: p for p in result.parts}
    assert list(by_sku) == ["A000023020512", "A000023525142", "A000040110080", "B008081420280"]

    washer = by_sku["A000023020512"]  # the repeat in row 6 is a recount: its count and bin are taken
    assert (washer.name, washer.unit_cost) == ("THRUST WASHER(PRESSURE DISC)MCED", Decimal("150.72"))
    assert (washer.quantity, washer.counted, washer.bin) == (Decimal(4), True, "A49A")

    seal = by_sku["A000023525142"]  # part number upper-cased; physical count wins over closing qty
    assert (seal.name, seal.quantity, seal.bin, seal.counted) == ("OIL SEAL", Decimal(12), "B3", True)
    assert seal.unit_cost == Decimal("114.71")  # closing value / closing qty, not / counted qty
    assert seal.columns == {
        "dms_bin": "NO BIN", "dms_category": "00001", "movement_class": "M4", "abc_class": "C", "hml_class": "L",
        "ris_class": "S", "sheet_closing_qty": Decimal("19.00"), "sheet_closing_value": Decimal("2179.48"),
        "sheet_actual_qty": Decimal("12.00"),
    }
    assert washer.columns["sheet_actual_qty"] == Decimal("4.00")  # recount taken from the repeat row

    assert by_sku["A000040110080"].unit_cost is None  # no stock, so no unit cost to derive

    gasket = by_sku["B008081420280"]  # description shifted one column right by hand
    assert (gasket.name, gasket.description, gasket.quantity) == ("GAEKET INTAKE MIDDLE", "GAS", Decimal(0))

    assert result.skipped == ["row 5: no part number (BOSH PUMP GASKET)"]
    assert result.duplicates == ["row 6: A000023020512 repeats row 1; took its count 4 and bin A49A"]


def _setup(w):
    db = w.db()
    user = db.scalar(select(User).where(User.email == "inventory@test.local"))
    tax = db.scalar(select(TaxRate).where(TaxRate.name == "GST 18%"))
    return db, user, tax


def test_import_creates_parts_with_opening_stock_and_rerun_is_safe(w):
    db, user, tax = _setup(w)
    with db:
        report = import_parts(db, parse_sheet(rows()).parts, user, markup_percent=Decimal(20), tax=tax)
        db.commit()
        assert len(report.created) == 4 and report.opening_units == Decimal(16)
        assert report.needs_price == ["A000040110080 ZERO STOCK PART", "B008081420280 GAEKET INTAKE MIDDLE"]

        seal = db.scalar(select(Part).where(Part.sku == "A000023525142"))
        assert (seal.purchase_cost, seal.selling_price, seal.tax_rate.name) == (Decimal("114.71"), Decimal("137.65"), "GST 18%")
        assert (seal.stock.qty_on_hand, seal.storage_location) == (Decimal(12), "B3")
        moves = db.scalars(select(InventoryMovement).where(InventoryMovement.part_id == seal.id)).all()
        assert [(m.movement_type, m.quantity, m.performed_by_id) for m in moves] == [(MovementType.RECEIVED, Decimal(12), user.id)]

        # Prices and stock maintained in the app are not overwritten by a re-run.
        seal.selling_price = Decimal("200.00")
        seal.stock.qty_on_hand = Decimal(3)
        db.commit()
        again = import_parts(db, parse_sheet(rows()).parts, user, markup_percent=Decimal(20), tax=tax)
        db.commit()
        assert (again.created, again.updated, again.unchanged) == ([], [], 4)
        db.refresh(seal)
        assert (seal.selling_price, seal.stock.qty_on_hand) == (Decimal("200.00"), Decimal(3))


def test_update_stock_adjusts_existing_parts_to_the_sheet(w):
    db, user, tax = _setup(w)
    with db:
        import_parts(db, parse_sheet(rows()).parts, user, markup_percent=Decimal(20), tax=tax)
        db.commit()
        recount = SHEET.replace("B3,12", "B4,10")
        report = import_parts(db, parse_sheet(rows(recount)).parts, user, markup_percent=Decimal(20), tax=tax, update_stock=True)
        db.commit()
        assert report.stock_adjusted == ["A000023525142: -2"]
        assert report.updated == ["A000023525142 (storage_location, sheet_actual_qty)"]
        seal = db.scalar(select(Part).where(Part.sku == "A000023525142"))
        assert (seal.stock.qty_on_hand, seal.storage_location) == (Decimal(10), "B4")
        last = db.scalars(select(InventoryMovement).where(InventoryMovement.part_id == seal.id).order_by(InventoryMovement.id)).all()[-1]
        assert (last.movement_type, last.quantity) == (MovementType.ADJUSTMENT, Decimal(-2))


def test_sheet_sync_imports_changes_only_and_leaves_stock_to_the_app(w, monkeypatch):
    from app.core.database import SessionLocal
    from app.workers import sheet_sync_worker

    sheet = {"text": SHEET}
    monkeypatch.setattr(sheet_sync_worker, "read_rows", lambda url: rows(sheet["text"]))
    digest = sheet_sync_worker.sync_once(SessionLocal, "https://example.invalid/sheet", None)
    with w.db() as db:
        seal = db.scalar(select(Part).where(Part.sku == "A000023525142"))
        assert seal.stock.qty_on_hand == Decimal(12)
        seal.stock.qty_on_hand = Decimal(7)  # parts issued to jobs in the app
        db.commit()

    # Unchanged sheet: nothing is imported.
    assert sheet_sync_worker.sync_once(SessionLocal, "https://example.invalid/sheet", digest) == digest

    # Staff edit the sheet: new bin and count, plus a new part. The bin follows; the stock does not.
    sheet["text"] = SHEET.replace("B3,12", "B4,10").replace(
        "7,,,,", "7,NEW-PART-1,AIR FILTER,,NO BIN,00001,,M5,C,,L,S,2,,,500,,,,,,\n8,,,,")
    assert sheet_sync_worker.sync_once(SessionLocal, "https://example.invalid/sheet", digest) != digest
    with w.db() as db:
        seal = db.scalar(select(Part).where(Part.sku == "A000023525142"))
        assert (seal.storage_location, seal.stock.qty_on_hand) == ("B4", Decimal(7))
        assert (seal.movement_class, seal.sheet_closing_qty, seal.sheet_actual_qty) == ("M4", Decimal(19), Decimal(10))
        added = db.scalar(select(Part).where(Part.sku == "NEW-PART-1"))
        assert (added.name, added.purchase_cost, added.stock.qty_on_hand) == ("AIR FILTER", Decimal("250.00"), Decimal(2))


def test_parts_sheet_link_is_given_to_parts_staff_only(w, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "parts_sheet_url", "")
    assert w.call("manager", "GET", "/parts-sheet").status_code == 404  # not configured
    assert w.ok("manager", "GET", "/features")["parts_sheet"] is False

    monkeypatch.setattr(get_settings(), "parts_sheet_url", "https://docs.google.com/spreadsheets/d/abc-123_X/edit?usp=sharing")
    for role in ("manager", "inventory", "admin"):
        assert w.ok(role, "GET", "/parts-sheet")["url"] == "https://docs.google.com/spreadsheets/d/abc-123_X/edit"
    assert w.ok("manager", "GET", "/features")["parts_sheet"] is True
