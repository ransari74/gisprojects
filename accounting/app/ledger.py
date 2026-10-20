"""Double-entry ledger: posting, balances and the core financial statements."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, JournalEntry, JournalLine

DEBIT_NORMAL = {"asset", "expense"}


class LedgerError(ValueError):
    pass


@dataclass
class Line:
    account_code: str
    debit: int = 0
    credit: int = 0
    description: str = ""


def accounts_by_code(db: Session) -> dict[str, Account]:
    return {a.code: a for a in db.scalars(select(Account))}


def validate_lines(db: Session, lines: list[Line]) -> None:
    accounts = accounts_by_code(db)
    if len(lines) < 2:
        raise LedgerError("An entry needs at least two lines")
    for line in lines:
        if line.account_code not in accounts:
            raise LedgerError(f"Unknown account code {line.account_code}")
        if not accounts[line.account_code].is_active:
            raise LedgerError(f"Account {line.account_code} is inactive")
        if line.debit < 0 or line.credit < 0:
            raise LedgerError("Debits and credits must be non-negative")
        if (line.debit > 0) == (line.credit > 0):
            raise LedgerError("Each line must have either a debit or a credit, not both")
    debits = sum(l.debit for l in lines)
    credits = sum(l.credit for l in lines)
    if debits != credits:
        raise LedgerError(f"Entry does not balance: debits {debits / 100:.2f} != credits {credits / 100:.2f}")


def post_entry(db: Session, entry_date: date, memo: str, lines: list[Line], source: str = "manual") -> JournalEntry:
    """Validate and add an entry to the session. The caller commits."""
    # Collapse zero lines so callers can pass optional amounts (e.g. a zero ITC) unconditionally.
    lines = [l for l in lines if l.debit or l.credit]
    validate_lines(db, lines)
    accounts = accounts_by_code(db)
    entry = JournalEntry(date=entry_date, memo=memo, source=source)
    for line in lines:
        entry.lines.append(
            JournalLine(
                account_id=accounts[line.account_code].id,
                debit=line.debit,
                credit=line.credit,
                description=line.description,
            )
        )
    db.add(entry)
    db.flush()
    return entry


def account_movements(
    db: Session,
    start: date | None = None,
    end: date | None = None,
    exclude_sources: tuple[str, ...] = (),
) -> dict[str, tuple[int, int]]:
    """Total (debits, credits) per account code for entries dated within [start, end]."""
    q = (
        select(Account.code, func.coalesce(func.sum(JournalLine.debit), 0), func.coalesce(func.sum(JournalLine.credit), 0))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .group_by(Account.code)
    )
    if start:
        q = q.where(JournalEntry.date >= start)
    if end:
        q = q.where(JournalEntry.date <= end)
    if exclude_sources:
        q = q.where(JournalEntry.source.not_in(exclude_sources))
    return {code: (int(d), int(c)) for code, d, c in db.execute(q)}


def natural_balance(account_type: str, debits: int, credits: int) -> int:
    return debits - credits if account_type in DEBIT_NORMAL else credits - debits


def trial_balance(db: Session, as_of: date | None = None) -> dict:
    moves = account_movements(db, end=as_of)
    rows, total_dr, total_cr = [], 0, 0
    for acct in sorted(accounts_by_code(db).values(), key=lambda a: a.code):
        d, c = moves.get(acct.code, (0, 0))
        net = d - c
        if net == 0:
            continue
        dr, cr = (net, 0) if net > 0 else (0, -net)
        total_dr += dr
        total_cr += cr
        rows.append({"code": acct.code, "name": acct.name, "type": acct.type, "debit": dr, "credit": cr})
    return {"as_of": as_of, "rows": rows, "total_debit": total_dr, "total_credit": total_cr}


def _section(db: Session, moves, types: tuple[str, ...]) -> list[dict]:
    rows = []
    for acct in sorted(accounts_by_code(db).values(), key=lambda a: a.code):
        if acct.type not in types:
            continue
        d, c = moves.get(acct.code, (0, 0))
        bal = natural_balance(acct.type, d, c)
        if bal:
            rows.append({"code": acct.code, "name": acct.name, "amount": bal})
    return rows


def income_statement(db: Session, start: date, end: date) -> dict:
    moves = account_movements(db, start, end)
    revenue = _section(db, moves, ("revenue",))
    expenses = _section(db, moves, ("expense",))
    cogs = [r for r in expenses if r["code"].startswith("5")]
    opex = [r for r in expenses if not r["code"].startswith("5")]
    total_revenue = sum(r["amount"] for r in revenue)
    total_cogs = sum(r["amount"] for r in cogs)
    total_opex = sum(r["amount"] for r in opex)
    return {
        "start": start,
        "end": end,
        "revenue": revenue,
        "total_revenue": total_revenue,
        "cost_of_goods_sold": cogs,
        "gross_profit": total_revenue - total_cogs,
        "operating_expenses": opex,
        "total_operating_expenses": total_opex,
        "net_income": total_revenue - total_cogs - total_opex,
    }


def balance_sheet(db: Session, as_of: date) -> dict:
    moves = account_movements(db, end=as_of)
    assets = _section(db, moves, ("asset",))
    liabilities = _section(db, moves, ("liability",))
    equity = _section(db, moves, ("equity",))
    # Revenue and expense accounts are never closed here, so their running total
    # is the earnings not yet moved to retained earnings.
    earnings = sum(r["amount"] for r in _section(db, moves, ("revenue",))) - sum(
        r["amount"] for r in _section(db, moves, ("expense",))
    )
    if earnings:
        equity.append({"code": "", "name": "Current Earnings (unclosed)", "amount": earnings})
    total_assets = sum(r["amount"] for r in assets)
    total_liabilities = sum(r["amount"] for r in liabilities)
    total_equity = sum(r["amount"] for r in equity)
    return {
        "as_of": as_of,
        "assets": assets,
        "total_assets": total_assets,
        "liabilities": liabilities,
        "total_liabilities": total_liabilities,
        "equity": equity,
        "total_equity": total_equity,
        "balanced": total_assets == total_liabilities + total_equity,
    }
