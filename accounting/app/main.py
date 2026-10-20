"""FastAPI app: REST API under /api, single-page UI at /.

Request bodies take dollar amounts; every amount in a response is integer cents.
"""
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, services
from app.ai.claude import AIUnavailable, ClaudeService, get_ai
from app.chart_of_accounts import seed_accounts
from app.db import Base, SessionLocal, engine, get_db
from app.ledger import Line, LedgerError, balance_sheet, income_statement, post_entry, trial_balance, validate_lines
from app.models import Account, BankTransaction, Bill, Contact, Employee, Invoice, JournalEntry, PayStub
from app.schemas import (
    AccountIn, AskIn, BankImportIn, BankPostIn, BillIn, ContactIn, DraftIn, EmployeeIn, GstRemitIn,
    InvoiceIn, JournalEntryIn, PaymentIn, PayrollPreviewIn, PayRunIn,
)
from app.money import to_cents
from app.tax import corporate, gst as gst_mod, payroll as payroll_mod

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_accounts(db)
    yield


def require_key(x_api_key: str = Header(default="")):
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(401, "Invalid or missing X-API-Key")


app = FastAPI(title="Alberta Business Accounting", lifespan=lifespan)
api = FastAPI(dependencies=[Depends(require_key)])


@api.exception_handler(LedgerError)
async def ledger_error(_, exc: LedgerError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@api.exception_handler(AIUnavailable)
async def ai_error(_, exc: AIUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def need_ai(ai: ClaudeService | None = Depends(get_ai)) -> ClaudeService:
    if ai is None:
        raise HTTPException(503, "AI features are disabled (ACCOUNTING_AI_ENABLED=0)")
    return ai


def year_bounds(start: date | None, end: date | None) -> tuple[date, date]:
    today = date.today()
    return start or date(today.year, 1, 1), end or today


def entry_out(e: JournalEntry) -> dict:
    return {
        "id": e.id,
        "date": e.date,
        "memo": e.memo,
        "source": e.source,
        "lines": [{"account_code": l.account.code, "account_name": l.account.name, "debit": l.debit, "credit": l.credit, "description": l.description} for l in e.lines],
    }


def row(obj, *exclude) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}


# ---------- Settings ----------

@api.get("/settings")
def settings():
    return {"business_name": config.BUSINESS_NAME, "gst_number": config.GST_NUMBER, "province": "AB", "ai_enabled": config.AI_ENABLED, "model": config.CLAUDE_MODEL}


# ---------- Accounts & journal ----------

@api.get("/accounts")
def list_accounts(db: Session = Depends(get_db)):
    return [row(a) for a in db.scalars(select(Account).order_by(Account.code))]


@api.post("/accounts", status_code=201)
def add_account(data: AccountIn, db: Session = Depends(get_db)):
    if db.scalar(select(Account).where(Account.code == data.code)):
        raise HTTPException(409, f"Account {data.code} already exists")
    acct = Account(**data.model_dump())
    db.add(acct)
    db.commit()
    return row(acct)


@api.get("/journal")
def list_journal(start: date | None = None, end: date | None = None, limit: int = 200, db: Session = Depends(get_db)):
    q = select(JournalEntry).order_by(JournalEntry.date.desc(), JournalEntry.id.desc()).limit(limit)
    if start:
        q = q.where(JournalEntry.date >= start)
    if end:
        q = q.where(JournalEntry.date <= end)
    return [entry_out(e) for e in db.scalars(q)]


@api.post("/journal", status_code=201)
def add_journal(data: JournalEntryIn, db: Session = Depends(get_db)):
    lines = [Line(l.account_code, to_cents(l.debit), to_cents(l.credit), l.description) for l in data.lines]
    entry = post_entry(db, data.date, data.memo, lines, source=data.source if data.source in ("manual", "ai") else "manual")
    db.commit()
    return entry_out(entry)


# ---------- Contacts, invoices, bills ----------

@api.get("/contacts")
def list_contacts(kind: str | None = None, db: Session = Depends(get_db)):
    q = select(Contact).order_by(Contact.name)
    if kind:
        q = q.where(Contact.kind == kind)
    return [row(c) for c in db.scalars(q)]


@api.post("/contacts", status_code=201)
def add_contact(data: ContactIn, db: Session = Depends(get_db)):
    c = Contact(**data.model_dump())
    db.add(c)
    db.commit()
    return row(c)


def invoice_out(inv: Invoice) -> dict:
    return row(inv) | {"customer": inv.customer.name, "lines": [row(l, "invoice_id") for l in inv.lines]}


@api.get("/invoices")
def list_invoices(status: str | None = None, db: Session = Depends(get_db)):
    q = select(Invoice).order_by(Invoice.issue_date.desc())
    if status:
        q = q.where(Invoice.status == status)
    return [invoice_out(i) for i in db.scalars(q)]


@api.post("/invoices", status_code=201)
def add_invoice(data: InvoiceIn, db: Session = Depends(get_db)):
    return invoice_out(services.create_invoice(db, data))


@api.post("/invoices/{invoice_id}/payments")
def pay_invoice(invoice_id: int, data: PaymentIn, db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id) or _404("Invoice")
    return invoice_out(services.pay_invoice(db, inv, data))


@api.get("/bills")
def list_bills(db: Session = Depends(get_db)):
    return [row(b) for b in db.scalars(select(Bill).order_by(Bill.date.desc()))]


@api.post("/bills", status_code=201)
def add_bill(data: BillIn, db: Session = Depends(get_db)):
    return row(services.create_bill(db, data))


def _404(what: str):
    raise HTTPException(404, f"{what} not found")


# ---------- Bank feed (rules + AI categorization) ----------

@api.post("/bank/import", status_code=201)
def bank_import(data: BankImportIn, db: Session = Depends(get_db), ai: ClaudeService | None = Depends(get_ai)):
    txns, note = services.import_bank(db, data, ai)
    return {"imported": [row(t) for t in txns], "note": note}


@api.get("/bank/transactions")
def bank_list(status: str | None = "pending", db: Session = Depends(get_db)):
    q = select(BankTransaction).order_by(BankTransaction.date)
    if status:
        q = q.where(BankTransaction.status == status)
    return [row(t) for t in db.scalars(q)]


@api.post("/bank/transactions/{txn_id}/post")
def bank_post(txn_id: int, data: BankPostIn, db: Session = Depends(get_db)):
    txn = db.get(BankTransaction, txn_id) or _404("Transaction")
    return row(services.post_bank_txn(db, txn, data.account_code, data.gst_included))


# ---------- Payroll ----------

@api.get("/employees")
def list_employees(db: Session = Depends(get_db)):
    return [row(e) for e in db.scalars(select(Employee).order_by(Employee.name))]


@api.post("/employees", status_code=201)
def add_employee(data: EmployeeIn, db: Session = Depends(get_db)):
    return row(services.create_employee(db, data))


@api.post("/payroll/preview")
def payroll_preview(data: PayrollPreviewIn):
    return payroll_mod.calculate(to_cents(data.gross), data.pay_periods, data.year).as_dict()


@api.post("/payroll/run", status_code=201)
def payroll_run(data: PayRunIn, db: Session = Depends(get_db)):
    stubs = services.run_payroll(db, data.pay_date, data.employee_ids)
    return [row(s) | {"employee": s.employee.name} for s in stubs]


@api.get("/payroll/stubs")
def payroll_stubs(db: Session = Depends(get_db)):
    return [row(s) | {"employee": s.employee.name} for s in db.scalars(select(PayStub).order_by(PayStub.pay_date.desc()))]


# ---------- Reports & tax ----------

@api.get("/reports/trial-balance")
def report_tb(as_of: date | None = None, db: Session = Depends(get_db)):
    return trial_balance(db, as_of)


@api.get("/reports/income-statement")
def report_pnl(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    return income_statement(db, *year_bounds(start, end))


@api.get("/reports/balance-sheet")
def report_bs(as_of: date | None = None, db: Session = Depends(get_db)):
    return balance_sheet(db, as_of or date.today())


@api.get("/reports/aged-receivables")
def report_ar(as_of: date | None = None, db: Session = Depends(get_db)):
    return services.aged_receivables(db, as_of or date.today())


@api.get("/tax/gst-return")
def tax_gst(start: date, end: date, db: Session = Depends(get_db)):
    return gst_mod.gst_return(db, start, end)


@api.post("/tax/gst-remit", status_code=201)
def tax_gst_remit(data: GstRemitIn, db: Session = Depends(get_db)):
    return services.remit_gst(db, data)


@api.get("/tax/corporate-estimate")
def tax_corp(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    return corporate.estimate(db, *year_bounds(start, end))


# ---------- AI ----------

def _accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).order_by(Account.code)))


def _checked_draft(db: Session, draft) -> dict:
    """Return the AI draft with the ledger's verdict, so the UI can show problems before posting."""
    lines = services.draft_to_lines(draft)
    try:
        validate_lines(db, [l for l in lines if l.debit or l.credit])
        problem = None
    except LedgerError as e:
        problem = str(e)
    return draft.model_dump() | {"valid": problem is None, "problem": problem}


@api.post("/ai/draft-entry")
def ai_draft(data: DraftIn, db: Session = Depends(get_db), ai: ClaudeService = Depends(need_ai)):
    return _checked_draft(db, ai.draft_entry(_accounts(db), text=data.text))


ALLOWED_UPLOADS = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}


@api.post("/ai/receipt")
async def ai_receipt(file: UploadFile = File(...), note: str = Form(""), db: Session = Depends(get_db), ai: ClaudeService = Depends(need_ai)):
    if file.content_type not in ALLOWED_UPLOADS:
        raise HTTPException(415, f"Unsupported file type {file.content_type}")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "File larger than 10 MB")
    return _checked_draft(db, ai.draft_entry(_accounts(db), text=note, image=data, media_type=file.content_type))


@api.post("/ai/ask")
def ai_ask(data: AskIn, db: Session = Depends(get_db), ai: ClaudeService = Depends(need_ai)):
    start, end = year_bounds(data.start, data.end)
    return {"answer": ai.ask(data.question, services.snapshot(db, start, end), _accounts(db))}


app.mount("/api", api)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
