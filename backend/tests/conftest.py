"""Test harness.

* Uses a dedicated PostgreSQL database (TEST_DATABASE_URL, default fsc_test on the dev cluster),
  built with the real Alembic migrations and truncated before every test.
* Email, SMS and WhatsApp always go to in-memory fakes; a guard makes any real network send fail
  loudly. WhatsApp is off unless a test switches it on (tests/test_whatsapp.py).
"""
import os

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://fsc@localhost:5544/fsc_test")
assert "test" in TEST_DB.rsplit("/", 1)[-1], "Refusing to run tests against a database not named *test*"
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=TEST_DB,
    BCRYPT_ROUNDS="4",
    JWT_SECRET="test-secret-test-secret-test-secret-1234",
    WEBHOOK_SECRET="test-webhook-secret",
    PUBLIC_BASE_URL="https://service.test",
    EMAIL_PROVIDER="dev",
    SMS_PROVIDER="dev",
    WHATSAPP_PROVIDER="disabled",
    WHATSAPP_APP_SECRET="test-whatsapp-app-secret",
    WHATSAPP_VERIFY_TOKEN="test-whatsapp-verify-token",
    # Never let real credentials from a developer's .env reach the tests.
    SMTP_HOST="", SMTP_USERNAME="", SMTP_PASSWORD="", EMAIL_SENDER_ADDRESS="", MSG91_AUTH_KEY="",
    WHATSAPP_ACCESS_TOKEN="", WHATSAPP_PHONE_NUMBER_ID="",
    LOGIN_RATE_LIMIT_PER_MINUTE="1000",
    PUBLIC_LINK_RATE_LIMIT_PER_MINUTE="1000",
)

from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.integrations import registry  # noqa: E402
from app.integrations.base import SendResult  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, InventoryStock, LabourOperation, Part, Role, TaxRate, User  # noqa: E402
from app.models.enums import RoleCode  # noqa: E402
from app.services.bootstrap import ensure_reference_data  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "Test@12345678"


class FakeProvider:
    """In-memory provider. `script` is a queue of outcomes for upcoming sends:
    'ok' | 'temp' | 'perm' | 'raise'. When empty, sends succeed."""

    supports_receipts = True
    simulated = False

    def __init__(self, name: str):
        self.name = name
        self.sent: list = []       # contents accepted
        self.calls: list = []      # (content, idempotency_key) for every call
        self.script: list[str] = []

    def send(self, content, idempotency_key):
        self.calls.append((content, idempotency_key))
        outcome = self.script.pop(0) if self.script else "ok"
        if outcome == "raise":
            raise ConnectionError("simulated outage")
        if outcome == "temp":
            return SendResult(False, error="temporary provider failure")
        if outcome == "perm":
            return SendResult(False, error="permanently rejected", permanent=True)
        self.sent.append(content)
        return SendResult(True, message_id=f"{self.name}-msg-{len(self.sent)}")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Any attempt to open SMTP or call an HTTP gateway during tests is an error."""

    def boom(*args, **kwargs):
        raise AssertionError("A real provider call was attempted during tests")

    monkeypatch.setattr("smtplib.SMTP", boom)
    monkeypatch.setattr("smtplib.SMTP_SSL", boom)
    monkeypatch.setattr("httpx.post", boom)


class World:
    def __init__(self, client: TestClient):
        self.client = client
        self.email = FakeProvider("fake-email")
        self.sms = FakeProvider("fake-sms")
        self.whatsapp = FakeProvider("fake-whatsapp")
        self.h: dict[str, dict] = {}
        self.ids: dict[str, int] = {}

    def login(self, role: str, email: str) -> None:
        r = self.client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        self.h[role] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.ids[role] = r.json()["user"]["id"]

    def call(self, role: str | None, method: str, url: str, **kw):
        return self.client.request(method, "/api" + url, headers=self.h[role] if role else {}, **kw)

    def ok(self, role: str | None, method: str, url: str, **kw):
        r = self.call(role, method, url, **kw)
        assert r.status_code < 300, f"{method} {url} -> {r.status_code}: {r.text}"
        return r.json() if r.content else None

    def db(self):
        return SessionLocal()


USERS = {
    "manager": ("manager@test.local", RoleCode.SERVICE_MANAGER),
    "mechanic": ("mechanic@test.local", RoleCode.MECHANIC),
    "mechanic2": ("mechanic2@test.local", RoleCode.MECHANIC),
    "inventory": ("inventory@test.local", RoleCode.INVENTORY_STAFF),
    "admin": ("admin@test.local", RoleCode.ADMIN),
}
PARTS = [("OIL", "Engine oil", "1000.00", "GST 18%", 10), ("PAD", "Brake pad set", "2400.00", "GST 28%", 1),
         ("CLUTCH", "Clutch kit", "10900.00", "GST 28%", 0), ("PAD-HD", "Brake pad set HD", "2850.00", "GST 28%", 5)]
LABOUR = [("LAB-GS", "General service", "2.0", "650.00"), ("LAB-BRK", "Brake pad replacement", "1.5", "650.00")]


@pytest.fixture
def w():
    limiter.reset()
    with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with SessionLocal() as db:
        ensure_reference_data(db)
        roles = {r.code: r for r in db.scalars(select(Role))}
        tax = {t.name: t for t in db.scalars(select(TaxRate))}
        for email, role in USERS.values():
            db.add(User(email=email, full_name=email.split("@")[0].title(), role_id=roles[role].id,
                        password_hash=hash_password(PASSWORD)))
        for code, name, hours, rate in LABOUR:
            db.add(LabourOperation(code=code, name=name, default_hours=Decimal(hours), hourly_rate=Decimal(rate), tax_rate=tax["GST 18%"]))
        for sku, name, price, tax_name, qty in PARTS:
            db.add(Part(sku=sku, name=name, selling_price=Decimal(price), purchase_cost=Decimal("1.00"), tax_rate=tax[tax_name],
                        reorder_threshold=Decimal(1), stock=InventoryStock(qty_on_hand=Decimal(qty), qty_reserved=Decimal(0))))
        db.commit()
    with TestClient(app) as client:
        world = World(client)
        registry.set_overrides(email=world.email, sms=world.sms, whatsapp=world.whatsapp)
        for role, (email, code) in USERS.items():
            if code == RoleCode.MECHANIC:
                continue  # mechanics do not sign in; the Service Manager records their work
            world.login(role, email)
        with SessionLocal() as db:
            for role, (email, code) in USERS.items():
                if code == RoleCode.MECHANIC:
                    world.ids[role] = db.scalar(select(User.id).where(User.email == email))
        with SessionLocal() as db:
            world.part = {p.sku: p.id for p in db.scalars(select(Part))}
            world.labour = {l.code: l.id for l in db.scalars(select(LabourOperation))}
        yield world
    registry.set_overrides(None, None, None)
