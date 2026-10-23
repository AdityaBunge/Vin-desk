import re
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")


def utcnow() -> datetime:
    return datetime.now(UTC)


def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value if value is not None else 0))


def money(value) -> Decimal:
    """Round to paise using commercial (half-up) rounding."""
    return D(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def normalise_registration(raw: str) -> str:
    """'mh 12-ab 1234' -> 'MH12AB1234' so searches and duplicate checks are consistent."""
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def normalise_indian_mobile(raw: str | None) -> str | None:
    """Return +91XXXXXXXXXX for a valid Indian mobile number, else None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    return None


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(raw: str | None) -> bool:
    return bool(raw and EMAIL_RE.match(raw.strip()))


_ONES = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen")
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _below_thousand(n: int) -> str:
    words = []
    if n >= 100:
        words += [_ONES[n // 100], "Hundred"]
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10])
        n %= 10
    if n:
        words.append(_ONES[n])
    return " ".join(words)


def _indian_words(n: int) -> str:
    if n == 0:
        return "Zero"
    words = []
    for size, name in ((10**7, "Crore"), (10**5, "Lakh"), (10**3, "Thousand")):
        if n >= size:
            chunk = _indian_words(n // size) if size == 10**7 else _below_thousand(n // size)
            words += [chunk, name]
            n %= size
    if n:
        words.append(_below_thousand(n))
    return " ".join(words)


def rupees_in_words(amount) -> str:
    """Indian invoice style: 46447 -> 'INR Forty Six Thousand Four Hundred Forty Seven Only'."""
    value = money(amount)
    rupees, paise = int(abs(value)), int((abs(value) * 100) % 100)
    text = f"INR {_indian_words(rupees)}"
    if paise:
        text += f" and {_indian_words(paise)} paise"
    return text + " Only"


# GST state codes (first two digits of a GSTIN).
GST_STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def gst_state(gstin: str | None) -> tuple[str, str] | None:
    """(state name, code) from a GSTIN, or None."""
    code = (gstin or "")[:2]
    return (GST_STATES[code], code) if code in GST_STATES else None


def financial_year_suffix(on: date) -> str:
    """Indian financial year (1 April - 31 March) as printed after the business name:
    15 Oct 2026 -> 'F.Y:26-27 - (from 1-Apr-26)'; 31 Mar 2026 -> 'F.Y:25-26 - (from 1-Apr-25)'."""
    start = on.year if on.month >= 4 else on.year - 1
    yy = start % 100
    return f"F.Y:{yy:02d}-{(yy + 1) % 100:02d} - (from 1-Apr-{yy:02d})"


def format_inr(amount) -> str:
    """Indian digit grouping: 1234567.5 -> '12,34,567.50'."""
    value = money(amount)
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}.{frac}"
