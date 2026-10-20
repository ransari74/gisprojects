"""Business workflows that turn documents (invoices, bills, bank lines, pay runs) into journal entries."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import chart_of_accounts as coa
from app.ai import rules
from app.ai.claude import AIUnavailable, ClaudeService
from app.ledger import Line, LedgerError, accounts_by_code, balance_sheet, income_statement, post_entry, trial_balance
from app.models import Account, BankTransaction, Bill, Contact, Employee, Invoice, InvoiceLine, PayStub
from app.money import round_cents, to_cents, to_dollars
from app.schemas import BankImportIn, BillIn, EmployeeIn, GstRemitIn, InvoiceIn, PaymentIn
from app.tax import gst as gst_mod
from app.tax import payroll as payroll_mod


def _require_account(db: Session, code: str, types: tuple[str, ...] | None = None) -> Account:
    acct = accounts_by_code(db).get(code)
    if acct is None:
        raise LedgerError(f"Unknown account code {code}")
    if types and acct.type not in types:
        raise LedgerError(f"Account {code} must be one of: {', '.join(types)}")
    return acct


# ---------- Invoices (sales) ----------

def create_invoice(db: Session, data: InvoiceIn) -> Invoice:
    customer = db.get(Contact, data.customer_id)
    if customer is None or customer.kind != "customer":
        raise LedgerError("customer_id must reference a customer contact")
    year = data.issue_date.year
    next_no = (db.scalar(select(func.count(Invoice.id))) or 0) + 1
    number = f"INV-{next_no:05d}"

    inv_lines, revenue_by_account, gst_total = [], {}, 0
    for l in data.lines:
        _require_account(db, l.account_code, ("revenue",))
        amount = round_cents(l.quantity * l.unit_price * 100)
        _, line_gst = gst_mod.split_gst(amount, gst_included=False, year=year, exempt=l.gst_exempt)
        gst_total += line_gst
        revenue_by_account[l.account_code] = revenue_by_account.get(l.account_code, 0) + amount
        inv_lines.append(
            InvoiceLine(
                description=l.description,
                quantity=str(l.quantity),
                unit_price=to_cents(l.unit_price),
                amount=amount,
                account_code=l.account_code,
                gst_exempt=l.gst_exempt,
            )
        )
    subtotal = sum(revenue_by_account.values())
    total = subtotal + gst_total

    lines = [Line(coa.ACCOUNTS_RECEIVABLE, debit=total, description=f"{number} {customer.name}")]
    lines += [Line(code, credit=amt, description=number) for code, amt in revenue_by_account.items()]
    lines.append(Line(coa.GST_COLLECTED, credit=gst_total, description=f"GST on {number}"))
    entry = post_entry(db, data.issue_date, f"Invoice {number} - {customer.name}", lines, source="invoice")

    inv = Invoice(
        number=number,
        customer_id=customer.id,
        issue_date=data.issue_date,
        due_date=data.issue_date + timedelta(days=data.due_days),
        subtotal=subtotal,
        gst=gst_total,
        total=total,
        entry_id=entry.id,
        lines=inv_lines,
    )
    db.add(inv)
    db.commit()
    return inv


def pay_invoice(db: Session, inv: Invoice, data: PaymentIn) -> Invoice:
    if inv.status == "paid":
        raise LedgerError("Invoice is already paid")
    _require_account(db, data.deposit_to, ("asset",))
    entry = post_entry(
        db,
        data.date,
        f"Payment received {inv.number}",
        [Line(data.deposit_to, debit=inv.total), Line(coa.ACCOUNTS_RECEIVABLE, credit=inv.total)],
        source="invoice_payment",
    )
    inv.status = "paid"
    inv.payment_entry_id = entry.id
    db.commit()
    return inv


def aged_receivables(db: Session, as_of: date) -> dict:
    buckets = {"current": 0, "1_30": 0, "31_60": 0, "61_90": 0, "over_90": 0}
    rows = []
    for inv in db.scalars(select(Invoice).where(Invoice.status == "open", Invoice.issue_date <= as_of)):
        days = (as_of - inv.due_date).days
        key = "current" if days <= 0 else "1_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "over_90"
        buckets[key] += inv.total
        rows.append({"number": inv.number, "customer": inv.customer.name, "due_date": inv.due_date, "days_overdue": max(0, days), "total": inv.total})
    return {"as_of": as_of, "buckets": buckets, "invoices": rows}


# ---------- Bills (purchases) ----------

def create_bill(db: Session, data: BillIn) -> Bill:
    _require_account(db, data.account_code, ("expense", "asset"))
    _require_account(db, data.paid_from, ("asset", "liability"))
    amount = to_cents(data.amount)
    subtotal, gst = gst_mod.split_gst(amount, data.gst_included, data.date.year, exempt=data.gst_exempt)
    itc = gst_mod.claimable_itc(gst, data.account_code)
    total = subtotal + gst
    entry = post_entry(
        db,
        data.date,
        f"Bill - {data.vendor_name}: {data.description}",
        [
            # Any GST that can't be claimed is part of the cost of the expense.
            Line(data.account_code, debit=subtotal + gst - itc, description=data.description),
            Line(coa.GST_ITC, debit=itc, description="ITC"),
            Line(data.paid_from, credit=total, description=data.vendor_name),
        ],
        source="bill",
    )
    bill = Bill(
        vendor_id=data.vendor_id,
        vendor_name=data.vendor_name,
        date=data.date,
        description=data.description,
        account_code=data.account_code,
        subtotal=subtotal,
        gst=gst,
        itc=itc,
        total=total,
        paid_from=data.paid_from,
        entry_id=entry.id,
    )
    db.add(bill)
    db.commit()
    return bill


# ---------- Bank feed ----------

def import_bank(db: Session, data: BankImportIn, ai: ClaudeService | None) -> tuple[list[BankTransaction], str | None]:
    """Store bank lines with a suggested account. Rules go first; low-confidence lines go to Claude."""
    _require_account(db, data.bank_account_code, ("asset", "liability"))
    accounts = list(db.scalars(select(Account).order_by(Account.code)))
    valid = {a.code for a in accounts if a.is_active}
    txns = []
    for t in data.transactions:
        cents = to_cents(t.amount)
        s = rules.categorize(t.description, cents, accounts)
        txns.append(
            BankTransaction(
                bank_account_code=data.bank_account_code,
                date=t.date,
                description=t.description,
                amount=cents,
                suggested_account=s.account_code,
                suggested_gst=s.gst_included,
                suggestion_source=s.source,
                suggestion_reason=s.reason,
                confidence=s.confidence,
            )
        )

    ai_note = None
    unsure = [i for i, t in enumerate(txns) if t.confidence == "low"]
    if data.use_ai and ai and unsure:
        payload = [{"index": i, "date": txns[i].date, "description": txns[i].description, "amount": str(to_dollars(txns[i].amount))} for i in unsure]
        try:
            for r in ai.categorize(payload, accounts):
                if r.index in unsure and r.account_code in valid and r.account_code != data.bank_account_code:
                    t = txns[r.index]
                    t.suggested_account = r.account_code
                    t.suggested_gst = r.gst_included
                    t.suggestion_source = "ai"
                    t.suggestion_reason = r.reason[:255]
                    t.confidence = r.confidence if r.confidence in ("high", "medium", "low") else "medium"
        except AIUnavailable as e:
            ai_note = f"AI categorization skipped: {e}"

    db.add_all(txns)
    db.commit()
    return txns, ai_note


def post_bank_txn(db: Session, txn: BankTransaction, account_code: str | None, gst_included: bool | None):
    if txn.status == "posted":
        raise LedgerError("Transaction already posted")
    code = account_code or txn.suggested_account
    acct = _require_account(db, code)
    with_gst = txn.suggested_gst if gst_included is None else gst_included
    amount = abs(txn.amount)
    subtotal, gst = gst_mod.split_gst(amount, gst_included=True, year=txn.date.year, exempt=not with_gst)
    if txn.amount < 0:
        itc = gst_mod.claimable_itc(gst, code)
        lines = [
            Line(code, debit=subtotal + gst - itc, description=txn.description),
            Line(coa.GST_ITC, debit=itc, description="ITC"),
            Line(txn.bank_account_code, credit=amount, description=txn.description),
        ]
    else:
        gst_account = coa.GST_COLLECTED if acct.type == "revenue" else coa.GST_ITC
        lines = [
            Line(txn.bank_account_code, debit=amount, description=txn.description),
            Line(code, credit=subtotal, description=txn.description),
            Line(gst_account, credit=gst, description="GST"),
        ]
    entry = post_entry(db, txn.date, txn.description, lines, source="bank")
    txn.status = "posted"
    txn.entry_id = entry.id
    txn.suggested_account = code
    txn.suggested_gst = with_gst
    db.commit()
    return txn


# ---------- Payroll ----------

def create_employee(db: Session, data: EmployeeIn) -> Employee:
    emp = Employee(
        name=data.name,
        pay_periods=data.pay_periods,
        gross_per_period=to_cents(data.gross_per_period),
        federal_claim=to_cents(data.federal_claim) if data.federal_claim is not None else None,
        alberta_claim=to_cents(data.alberta_claim) if data.alberta_claim is not None else None,
    )
    db.add(emp)
    db.commit()
    return emp


def year_to_date(db: Session, employee_id: int, before: date) -> payroll_mod.YearToDate:
    row = db.execute(
        select(func.coalesce(func.sum(PayStub.gross), 0), func.coalesce(func.sum(PayStub.cpp), 0), func.coalesce(func.sum(PayStub.cpp2), 0), func.coalesce(func.sum(PayStub.ei), 0)).where(
            PayStub.employee_id == employee_id,
            PayStub.pay_date >= date(before.year, 1, 1),
            PayStub.pay_date < before,
        )
    ).one()
    return payroll_mod.YearToDate(*map(int, row))


def run_payroll(db: Session, pay_date: date, employee_ids: list[int] | None) -> list[PayStub]:
    q = select(Employee)
    if employee_ids:
        q = q.where(Employee.id.in_(employee_ids))
    stubs = []
    for emp in db.scalars(q):
        d = payroll_mod.calculate(
            emp.gross_per_period,
            emp.pay_periods,
            pay_date.year,
            ytd=year_to_date(db, emp.id, pay_date),
            federal_claim_cents=emp.federal_claim,
            alberta_claim_cents=emp.alberta_claim,
        )
        entry = post_entry(
            db,
            pay_date,
            f"Payroll - {emp.name}",
            [
                Line(coa.WAGES, debit=d.gross, description=emp.name),
                Line(coa.EMPLOYER_PAYROLL_TAXES, debit=d.employer_total, description="Employer CPP/CPP2/EI"),
                Line(coa.CASH, credit=d.net, description=f"Net pay {emp.name}"),
                Line(coa.PAYROLL_REMITTANCES, credit=d.employee_total + d.employer_total, description="Source deductions owing to CRA"),
            ],
            source="payroll",
        )
        stub = PayStub(
            employee_id=emp.id,
            pay_date=pay_date,
            gross=d.gross,
            cpp=d.cpp,
            cpp2=d.cpp2,
            ei=d.ei,
            federal_tax=d.federal_tax,
            alberta_tax=d.alberta_tax,
            net=d.net,
            employer_cpp=d.employer_cpp + d.employer_cpp2,
            employer_ei=d.employer_ei,
            entry_id=entry.id,
        )
        db.add(stub)
        stubs.append(stub)
    db.commit()
    return stubs


# ---------- GST remittance ----------

def remit_gst(db: Session, data: GstRemitIn) -> dict:
    ret = gst_mod.gst_return(db, data.start, data.end)
    collected, itcs, net = ret["line_105_gst_collected"], ret["line_108_itcs"], ret["line_109_net_tax"]
    if collected == 0 and itcs == 0:
        raise LedgerError("No GST activity in that period")
    lines = [Line(coa.GST_COLLECTED, debit=collected), Line(coa.GST_ITC, credit=itcs)]
    if net > 0:
        lines.append(Line(data.paid_from, credit=net, description="GST remittance to CRA"))
    elif net < 0:
        lines.append(Line(data.paid_from, debit=-net, description="GST refund from CRA"))
    entry = post_entry(db, data.paid_on, f"GST return {data.start} to {data.end}", lines, source="gst_remittance")
    db.commit()
    return ret | {"entry_id": entry.id}


# ---------- Snapshot for AI Q&A ----------

def snapshot(db: Session, start: date, end: date) -> dict:
    return {
        "period": {"start": start, "end": end},
        "income_statement": income_statement(db, start, end),
        "balance_sheet": balance_sheet(db, end),
        "gst_for_period": gst_mod.gst_return(db, start, end),
        "receivables": aged_receivables(db, end),
        "pending_bank_transactions": db.scalar(select(func.count(BankTransaction.id)).where(BankTransaction.status == "pending")),
        "trial_balance": trial_balance(db, end)["rows"],
    }


def draft_to_lines(draft) -> list[Line]:
    return [Line(l.account_code, debit=to_cents(Decimal(str(l.debit))), credit=to_cents(Decimal(str(l.credit))), description=l.description) for l in draft.lines]
