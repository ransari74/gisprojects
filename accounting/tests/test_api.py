def _customer(client):
    return client.post("/api/contacts", json={"name": "Calgary Dental", "kind": "customer"}).json()["id"]


def test_accounts_seeded(client):
    codes = {a["code"] for a in client.get("/api/accounts").json()}
    assert {"1000", "1300", "2200", "6150"} <= codes


def test_unbalanced_entry_rejected(client):
    r = client.post("/api/journal", json={"date": "2026-01-05", "lines": [
        {"account_code": "1000", "debit": "100"},
        {"account_code": "3000", "credit": "90"},
    ]})
    assert r.status_code == 422
    assert "does not balance" in r.json()["detail"]


def test_invoice_payment_and_gst_return(client):
    cid = _customer(client)
    inv = client.post("/api/invoices", json={
        "customer_id": cid, "issue_date": "2026-02-01",
        "lines": [{"description": "Consulting", "quantity": "10", "unit_price": "150"}],
    }).json()
    assert (inv["subtotal"], inv["gst"], inv["total"]) == (150000, 7500, 157500)

    client.post("/api/bills", json={"vendor_name": "Telus", "date": "2026-02-10", "description": "Internet",
                                   "account_code": "6450", "amount": "105", "paid_from": "1000"})
    client.post("/api/bills", json={"vendor_name": "Tim Hortons", "date": "2026-02-11", "description": "Client coffee",
                                   "account_code": "6150", "amount": "21", "paid_from": "2100"})

    ret = client.get("/api/tax/gst-return", params={"start": "2026-01-01", "end": "2026-03-31"}).json()
    assert ret["line_101_sales"] == 150000
    assert ret["line_105_gst_collected"] == 7500
    assert ret["line_108_itcs"] == 500 + 50  # Telus full ITC, meals 50% of $1.00
    assert ret["line_109_net_tax"] == 7500 - 550

    paid = client.post(f"/api/invoices/{inv['id']}/payments", json={"date": "2026-02-20"}).json()
    assert paid["status"] == "paid"

    remit = client.post("/api/tax/gst-remit", json={"start": "2026-01-01", "end": "2026-03-31", "paid_on": "2026-04-15"})
    assert remit.status_code == 201
    tb = client.get("/api/reports/trial-balance").json()
    balances = {r["code"]: r for r in tb["rows"]}
    assert "2200" not in balances and "1300" not in balances  # cleared by remittance
    assert tb["total_debit"] == tb["total_credit"]
    # The remittance doesn't erase the period's return.
    again = client.get("/api/tax/gst-return", params={"start": "2026-01-01", "end": "2026-03-31"}).json()
    assert again["line_109_net_tax"] == 6950


def test_balance_sheet_balances(client):
    client.post("/api/journal", json={"date": "2026-01-01", "memo": "Owner investment", "lines": [
        {"account_code": "1000", "debit": "10000"}, {"account_code": "3000", "credit": "10000"}]})
    cid = _customer(client)
    client.post("/api/invoices", json={"customer_id": cid, "issue_date": "2026-01-10",
                                      "lines": [{"description": "Work", "unit_price": "2000"}]})
    client.post("/api/bills", json={"vendor_name": "Landlord", "date": "2026-01-15", "description": "Rent",
                                   "account_code": "6350", "amount": "1500", "gst_included": False})
    bs = client.get("/api/reports/balance-sheet", params={"as_of": "2026-12-31"}).json()
    assert bs["balanced"]
    pnl = client.get("/api/reports/income-statement", params={"start": "2026-01-01", "end": "2026-12-31"}).json()
    assert pnl["net_income"] == 200000 - 150000


def test_bank_import_rules_then_ai(client, fake_ai):
    r = client.post("/api/bank/import", json={"transactions": [
        {"date": "2026-03-01", "description": "PETRO-CANADA #1234 CALGARY", "amount": "-63.00"},
        {"date": "2026-03-02", "description": "NOTION LABS INC", "amount": "-21.00"},
        {"date": "2026-03-03", "description": "MONTHLY FEE", "amount": "-4.95"},
    ]}).json()
    by_desc = {t["description"]: t for t in r["imported"]}
    assert by_desc["PETRO-CANADA #1234 CALGARY"]["suggested_account"] == "6500"
    assert by_desc["PETRO-CANADA #1234 CALGARY"]["suggestion_source"] == "rules"
    assert by_desc["NOTION LABS INC"]["suggested_account"] == "6250"
    assert by_desc["NOTION LABS INC"]["suggestion_source"] == "ai"
    assert by_desc["MONTHLY FEE"]["suggested_gst"] is False
    # Only the unmatched line went to the AI.
    assert [t["description"] for t in fake_ai.categorize_calls[0]] == ["NOTION LABS INC"]

    fuel = by_desc["PETRO-CANADA #1234 CALGARY"]
    posted = client.post(f"/api/bank/transactions/{fuel['id']}/post", json={}).json()
    assert posted["status"] == "posted"
    entry = client.get("/api/journal").json()[0]
    lines = {l["account_code"]: l for l in entry["lines"]}
    assert lines["6500"]["debit"] == 6000 and lines["1300"]["debit"] == 300 and lines["1000"]["credit"] == 6300

    assert client.post(f"/api/bank/transactions/{fuel['id']}/post", json={}).status_code == 422


def test_bank_import_survives_ai_outage(client, fake_ai):
    fake_ai.fail = True
    r = client.post("/api/bank/import", json={"transactions": [
        {"date": "2026-03-02", "description": "NOTION LABS INC", "amount": "-21.00"}]}).json()
    assert r["imported"][0]["suggested_account"] == "6990"
    assert "offline" in r["note"]


def test_payroll_run_posts_balanced_entry(client):
    emp = client.post("/api/employees", json={"name": "Sam", "pay_periods": 26, "gross_per_period": "2000"}).json()
    stubs = client.post("/api/payroll/run", json={"pay_date": "2026-01-16"}).json()
    assert stubs[0]["employee_id"] == emp["id"]
    assert stubs[0]["cpp"] == 11099
    tb = client.get("/api/reports/trial-balance").json()
    assert tb["total_debit"] == tb["total_credit"]
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows["6700"]["debit"] == 200000


def test_corporate_estimate_small_business_rate(client):
    cid = _customer(client)
    client.post("/api/invoices", json={"customer_id": cid, "issue_date": "2026-05-01",
                                      "lines": [{"description": "Project", "unit_price": "100000"}]})
    client.post("/api/bills", json={"vendor_name": "Keg", "date": "2026-05-02", "description": "Client dinner",
                                   "account_code": "6150", "amount": "1000", "gst_included": False})
    est = client.get("/api/tax/corporate-estimate", params={"start": "2026-01-01", "end": "2026-12-31"}).json()
    # Book income 100,000 - 1,025 (meals + unclaimable half of GST) ; add back half the meals cost
    assert est["meals_addback"] == 51250
    assert est["taxable_income"] == 10000000 - 102500 + 51250
    # 9% federal + 2% Alberta, each rounded to the cent
    assert abs(est["total_tax"] - est["taxable_income"] * 0.11) <= 1


def test_ai_draft_is_validated_and_postable(client):
    draft = client.post("/api/ai/draft-entry", json={"text": "Paid $105 at Staples with Visa"}).json()
    assert draft["valid"] is True
    r = client.post("/api/journal", json={"date": draft["date"], "memo": draft["memo"], "source": "ai", "lines": draft["lines"]})
    assert r.status_code == 201
    assert r.json()["source"] == "ai"


def test_ai_ask_uses_snapshot(client):
    r = client.post("/api/ai/ask", json={"question": "How am I doing?", "start": "2026-01-01", "end": "2026-12-31"})
    assert r.json()["answer"] == "Net income is 0 cents."


def test_ai_disabled_returns_503(client):
    from app.ai.claude import get_ai
    from app.main import api

    api.dependency_overrides[get_ai] = lambda: None
    assert client.post("/api/ai/ask", json={"question": "hi"}).status_code == 503


def test_missing_credentials_degrade_to_rules(client):
    import anthropic

    from app.ai.claude import ClaudeService, get_ai
    from app.main import api

    no_creds = ClaudeService(client=anthropic.Anthropic(api_key=None, auth_token=None))
    api.dependency_overrides[get_ai] = lambda: no_creds
    r = client.post("/api/bank/import", json={"transactions": [
        {"date": "2026-03-02", "description": "NOTION LABS INC", "amount": "-21.00"}]})
    assert r.status_code == 201
    assert "credentials" in r.json()["note"]
    assert client.post("/api/ai/ask", json={"question": "hi"}).status_code == 503
