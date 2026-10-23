"""Import the spare-parts catalogue and stock from the workshop's closing-stock sheet.

    python -m app.import_parts "https://docs.google.com/spreadsheets/d/<id>/edit"  --dry-run
    python -m app.import_parts "https://docs.google.com/spreadsheets/d/<id>/edit"
    python -m app.import_parts parts.csv --update-stock

The sheet is the dealer system's "closing stock" report: Part Number, Part Description, Closing
Qty., Closing Value (landed cost) and, for counted parts, BIN NUMBER and ACTUAL QUANTITY. Columns
are found by their header names. The sheet must be shared as "anyone with the link can view".

Safe to re-run:
* new part numbers are created, with their opening stock recorded as a RECEIVED movement;
* existing parts get the sheet's name, landed cost and bin; their selling price, tax and stock are
  left alone (they are maintained in the app), unless --update-stock is given, which adjusts
  on-hand stock to the sheet's quantity with an audited ADJUSTMENT.

Opening quantity = ACTUAL QUANTITY (physical count) when present, else Closing Qty.
Selling price of a new part = landed unit cost + --markup percent (default 20).
"""
import argparse
import csv
import io
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.errors import DomainError
from app.core.utils import ZERO, money
from app.models import InventoryStock, Part, Role, TaxRate, User
from app.models.enums import RoleCode
from app.services import inventory
from app.services.common import audit

OPENING_REASON = "Opening stock from the parts sheet"
CODE_COLUMNS = (("movement_class", "MOVEMENT"), ("abc_class", "ABC"), ("hml_class", "HML"), ("ris_class", "RIS"))


class SheetError(Exception):
    """The sheet could not be read or is not in the expected layout."""


@dataclass
class SheetPart:
    row: str  # the sheet's Sr.No., for messages
    sku: str
    name: str
    description: str = ""
    quantity: Decimal = ZERO
    unit_cost: Decimal | None = None  # landed cost per unit; None when the sheet gives no value
    bin: str = ""
    counted: bool = False  # quantity is a physical count
    # The sheet's own columns, kept on the part as last synced: Part attribute -> value.
    columns: dict[str, str | Decimal | None] = field(default_factory=dict)


@dataclass
class ParseResult:
    parts: list[SheetPart] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


def _key(header: str) -> str:
    return re.sub(r"[^A-Z]", "", header.upper())


def _number(raw: str) -> Decimal | None:
    raw = (raw or "").replace(",", "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _rounded(value: Decimal | None) -> Decimal | None:
    return None if value is None else money(value)


def parse_sheet(rows: list[list[str]]) -> ParseResult:
    header_at = next((i for i, r in enumerate(rows) if "PARTNUMBER" in map(_key, r)), None)
    if header_at is None:
        raise SheetError("No 'Part Number' header row found in the sheet.")
    cols = {}
    for i, h in enumerate(rows[header_at]):
        cols.setdefault(_key(h), i)  # first occurrence wins ("BIN" before "BIN NUMBER")
    for needed in ("PARTNUMBER", "PARTDESCRIPTION", "CLOSINGQTY"):
        if needed not in cols:
            raise SheetError(f"Column '{needed}' not found in the sheet header.")

    def cell(r: list[str], name: str, offset: int = 0) -> str:
        i = cols.get(name)
        return r[i + offset].strip() if i is not None and i + offset < len(r) else ""

    result = ParseResult()
    seen: dict[str, SheetPart] = {}
    for r in rows[header_at + 1:]:
        serial = r[0].strip() if r else ""
        if not serial.isdigit():
            continue
        # Hand-added rows put the description one column to the right, sometimes in both.
        texts = [t for t in (cell(r, "PARTDESCRIPTION"), cell(r, "PARTDESCRIPTION", 1)) if t]
        sku = re.sub(r"\s+", " ", cell(r, "PARTNUMBER")).upper()
        if not sku:
            if texts:
                result.skipped.append(f"row {serial}: no part number ({texts[0]})")
            continue
        if len(sku) > 40:
            result.skipped.append(f"row {serial}: part number longer than 40 characters ({sku})")
            continue
        texts.sort(key=len, reverse=True)
        name = re.sub(r"\s+", " ", texts[0] if texts else sku)[:160]
        description = texts[1] if len(texts) > 1 and texts[1] != texts[0] else ""

        closing_qty, closing_value = _number(cell(r, "CLOSINGQTY")), _number(cell(r, "CLOSINGVALUE"))
        counted_qty = _number(cell(r, "ACTUALQUANTITY"))
        unit_cost = money(closing_value / closing_qty) if closing_qty and closing_value is not None else None
        part = SheetPart(
            row=serial, sku=sku, name=name, description=description,
            quantity=counted_qty if counted_qty is not None else (closing_qty or ZERO),
            unit_cost=unit_cost, bin=cell(r, "BINNUMBER")[:60], counted=counted_qty is not None,
            columns={
                "dms_bin": cell(r, "BIN")[:30], "dms_category": cell(r, "CATEGORY")[:30],
                **{attr: cell(r, header)[:10] for attr, header in CODE_COLUMNS},
                "sheet_closing_qty": _rounded(closing_qty), "sheet_closing_value": _rounded(closing_value),
                "sheet_actual_qty": _rounded(counted_qty),
            },
        )
        if part.quantity < 0:
            result.skipped.append(f"row {serial}: negative quantity for {sku}")
            continue
        earlier = seen.get(sku)
        if earlier is not None:
            # A repeated part number is usually a hand-added recount: keep the first row, taking
            # the physical count and bin from the repeat when the first row has none.
            merged = []
            if part.counted and not earlier.counted:
                earlier.quantity, earlier.counted = part.quantity, True
                earlier.columns["sheet_actual_qty"] = part.columns["sheet_actual_qty"]
                merged.append(f"count {part.quantity}")
            if part.bin and not earlier.bin:
                earlier.bin = part.bin
                merged.append(f"bin {part.bin}")
            taken = f"; took its {' and '.join(merged)}" if merged else ""
            result.duplicates.append(f"row {serial}: {sku} repeats row {earlier.row}{taken}")
            continue
        seen[sku] = part
        result.parts.append(part)
    return result


def read_rows(source: str) -> list[list[str]]:
    if source.startswith(("http://", "https://")):
        url = source
        match = re.search(r"docs\.google\.com/spreadsheets/d/([^/]+)", source)
        if match:
            parsed = urllib.parse.urlparse(source)
            gid = urllib.parse.parse_qs(parsed.query).get("gid") or urllib.parse.parse_qs(parsed.fragment).get("gid")
            url = f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"
            if gid:
                url += f"&gid={gid[0]}"
        not_shared = "The link did not return CSV. Share the sheet as 'anyone with the link can view'."
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                if "text/csv" not in response.headers.get("Content-Type", ""):
                    raise SheetError(not_shared)
                text = response.read().decode("utf-8-sig")
        except urllib.error.HTTPError as exc:
            raise SheetError(f"{not_shared} (HTTP {exc.code})") from exc
        except urllib.error.URLError as exc:
            raise SheetError(f"Could not download the sheet: {exc.reason}") from exc
    else:
        with open(source, encoding="utf-8-sig", newline="") as f:
            text = f.read()
    return list(csv.reader(io.StringIO(text)))


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    stock_adjusted: list[str] = field(default_factory=list)
    stock_problems: list[str] = field(default_factory=list)
    needs_price: list[str] = field(default_factory=list)
    opening_units: Decimal = ZERO


def import_parts(
    db: Session, parts: list[SheetPart], user: User, *, markup_percent: Decimal, tax: TaxRate | None,
    update_stock: bool = False,
) -> ImportReport:
    report = ImportReport()
    existing = {p.sku: p for p in db.scalars(select(Part).where(Part.sku.in_([s.sku for s in parts])))}
    for item in parts:
        part = existing.get(item.sku)
        if part is None:
            cost = item.unit_cost or ZERO
            part = Part(
                sku=item.sku, name=item.name, description=item.description, purchase_cost=cost,
                selling_price=money(cost * (1 + markup_percent / Decimal(100))), tax_rate_id=tax.id if tax else None,
                reorder_threshold=ZERO, storage_location=item.bin, unit="NO",
                stock=InventoryStock(qty_on_hand=ZERO, qty_reserved=ZERO), **item.columns,
            )
            db.add(part)
            db.flush()
            if item.quantity > 0:
                inventory.receive_stock(db, part.id, item.quantity, user, OPENING_REASON)
                report.opening_units += item.quantity
            report.created.append(item.sku)
            if item.unit_cost is None:
                report.needs_price.append(f"{item.sku} {item.name}")
            continue

        changed = []
        for attr, value in (("name", item.name), ("description", item.description), ("storage_location", item.bin)):
            if value and getattr(part, attr) != value:
                setattr(part, attr, value)
                changed.append(attr)
        if item.unit_cost is not None and part.purchase_cost != item.unit_cost:
            part.purchase_cost = item.unit_cost
            changed.append("purchase_cost")
        for attr, value in item.columns.items():  # the sheet's own columns mirror it exactly
            if getattr(part, attr) != value:
                setattr(part, attr, value)
                changed.append(attr)
        if changed:
            report.updated.append(f"{item.sku} ({', '.join(changed)})")
        adjusted = False
        if update_stock:
            delta = item.quantity - part.stock.qty_on_hand
            if delta != 0:
                try:
                    with db.begin_nested():
                        inventory.adjust_stock(db, part.id, delta, user, "Stock set to the parts sheet quantity")
                    report.stock_adjusted.append(f"{item.sku}: {delta.normalize():+f}")
                    adjusted = True
                except DomainError as exc:
                    report.stock_problems.append(f"{item.sku}: {exc.detail}")
        if not changed and not adjusted:
            report.unchanged += 1
    audit(
        db, user, "parts.import", "part", None,
        f"Imported parts sheet: {len(report.created)} created, {len(report.updated)} updated",
        {"created": len(report.created), "updated": len(report.updated), "stock_adjusted": len(report.stock_adjusted)},
    )
    return report


def find_tax(db: Session, name: str) -> TaxRate | None:
    if name.lower() == "none":
        return None
    tax = db.scalar(select(TaxRate).where(TaxRate.name == name))
    if tax is None:
        raise SheetError(f"Tax rate '{name}' not found. Existing: {', '.join(db.scalars(select(TaxRate.name)))}")
    return tax


def actor(db: Session, email: str | None) -> User:
    stmt = select(User).join(Role).where(User.is_active.is_(True))
    if email:
        user = db.scalar(stmt.where(User.email == email.lower()))
        if user is None:
            raise SheetError(f"No active user {email}.")
        return user
    for role in (RoleCode.INVENTORY_STAFF, RoleCode.ADMIN):
        user = db.scalar(stmt.where(Role.code == role).order_by(User.id))
        if user is not None:
            return user
    raise SheetError("No active inventory or administrator user to record the stock movements; pass --user.")


def _print_list(title: str, items: list[str], limit: int = 15) -> None:
    if not items:
        return
    print(f"\n{title} ({len(items)}):")
    for line in items[:limit]:
        print(f"  - {line}")
    if len(items) > limit:
        print(f"  ... and {len(items) - limit} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="Google Sheets link or a local .csv file")
    parser.add_argument("--markup", type=Decimal, default=Decimal(20), help="selling price markup %% on landed cost for new parts")
    parser.add_argument("--tax", default="GST 18%", help="tax rate name for new parts, or 'none' (default: GST 18%%)")
    parser.add_argument("--update-stock", action="store_true", help="adjust existing parts' on-hand stock to the sheet")
    parser.add_argument("--user", help="email of the user recorded on stock movements (default: first inventory user)")
    parser.add_argument("--dry-run", action="store_true", help="show what would change without saving")
    args = parser.parse_args(argv)

    try:
        parsed = parse_sheet(read_rows(args.source))
        with SessionLocal() as db:
            tax = find_tax(db, args.tax)
            user = actor(db, args.user)
            report = import_parts(db, parsed.parts, user, markup_percent=args.markup, tax=tax, update_stock=args.update_stock)
            if args.dry_run:
                db.rollback()
            else:
                db.commit()
    except SheetError as exc:
        raise SystemExit(str(exc)) from exc

    counted = sum(1 for p in parsed.parts if p.counted)
    print(f"{'DRY RUN - nothing saved. ' if args.dry_run else ''}Read {len(parsed.parts)} parts from the sheet "
          f"({counted} with a physical count).")
    print(f"Created {len(report.created)} parts with {report.opening_units} units of opening stock; "
          f"updated {len(report.updated)}; unchanged {report.unchanged}.")
    if args.update_stock:
        print(f"Stock adjusted on {len(report.stock_adjusted)} existing parts.")
    _print_list("Updated parts", report.updated)
    _print_list("Stock adjustments", report.stock_adjusted)
    _print_list("Stock NOT adjusted", report.stock_problems)
    _print_list("New parts with no cost in the sheet: set their price in Parts", report.needs_price, limit=40)
    _print_list("Rows skipped", parsed.skipped, limit=40)
    _print_list("Duplicate part numbers", parsed.duplicates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
