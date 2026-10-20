import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["ACCOUNTING_DB_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ACCOUNTING_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai.claude import AIUnavailable, CategorizedTxn, DraftEntry, DraftLine, get_ai  # noqa: E402
from app.chart_of_accounts import seed_accounts  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import api, app  # noqa: E402


class FakeAI:
    """Stands in for ClaudeService so tests never hit the network."""

    def __init__(self):
        self.categorize_calls = []
        self.fail = False

    def categorize(self, txns, accounts):
        self.categorize_calls.append(txns)
        if self.fail:
            raise AIUnavailable("offline")
        return [CategorizedTxn(index=t["index"], account_code="6250", gst_included=True, confidence="high", reason="looks like SaaS") for t in txns]

    def draft_entry(self, accounts, text="", image=None, media_type="image/jpeg", today=None):
        return DraftEntry(
            date="2026-03-04",
            memo="Staples office supplies",
            lines=[
                DraftLine(account_code="6200", debit=100.00, credit=0, description="supplies"),
                DraftLine(account_code="1300", debit=5.00, credit=0, description="GST"),
                DraftLine(account_code="2100", debit=0, credit=105.00, description="Visa"),
            ],
            explanation="Office supplies paid by credit card.",
            review_notes=[],
        )

    def ask(self, question, snapshot, accounts):
        return f"Net income is {snapshot['income_statement']['net_income']} cents."


@pytest.fixture
def fake_ai():
    return FakeAI()


@pytest.fixture
def client(fake_ai):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_accounts(db)
    api.dependency_overrides[get_ai] = lambda: fake_ai
    with TestClient(app) as c:
        yield c
    api.dependency_overrides.clear()
