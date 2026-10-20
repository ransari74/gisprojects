"""Deterministic keyword categorizer: runs first, and is the fallback when the AI is off."""
import re
from dataclasses import dataclass

from app import chart_of_accounts as coa
from app.models import Account

# Descriptions that never carry GST: bank charges, payroll, taxes, transfers, loans.
NO_GST_ACCOUNTS = {"1010", "2100", "2300", "2400", "2500", "2600", "3200", "6100", "6600", "6700", "4900"}


@dataclass
class Suggestion:
    account_code: str
    gst_included: bool
    confidence: str  # high | medium | low
    reason: str
    source: str  # rules | ai


def _keywords(account: Account) -> list[str]:
    return [k.strip().lower() for k in account.keywords.split(",") if k.strip()]


def categorize(description: str, amount_cents: int, accounts: list[Account]) -> Suggestion:
    text = description.lower()
    best: tuple[int, Account, str] | None = None
    for acct in accounts:
        if not acct.is_active:
            continue
        # Deposits are matched against income/balance-sheet accounts; withdrawals against everything else.
        if amount_cents > 0 and acct.type == "expense":
            continue
        if amount_cents < 0 and acct.type == "revenue":
            continue
        for kw in _keywords(acct):
            if re.search(rf"\b{re.escape(kw)}\b", text) and (best is None or len(kw) > best[0]):
                best = (len(kw), acct, kw)
    if best:
        _, acct, kw = best
        return Suggestion(acct.code, acct.code not in NO_GST_ACCOUNTS, "medium", f'matched keyword "{kw}"', "rules")
    if amount_cents > 0:
        return Suggestion("4100", True, "low", "unmatched deposit; defaulted to service revenue", "rules")
    return Suggestion("6990", False, "low", "no keyword matched; needs review", "rules")
