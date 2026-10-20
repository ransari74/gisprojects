"""GST helpers and the GST/HST return (GST34) for an Alberta registrant."""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app import chart_of_accounts as coa
from app.ledger import account_movements, accounts_by_code
from app.money import round_cents
from app.tax.rates import rates_for

# Meals and entertainment: only 50% of the GST paid is claimable as an ITC.
ITC_LIMITED_ACCOUNTS = {coa.MEALS: Decimal("0.5")}


def split_gst(amount_cents: int, gst_included: bool, year: int, exempt: bool = False) -> tuple[int, int]:
    """Return (subtotal, gst) in cents for an amount that does or doesn't include GST."""
    if exempt:
        return amount_cents, 0
    rate = rates_for(year).gst_rate
    if gst_included:
        gst = round_cents(Decimal(amount_cents) * rate / (1 + rate))
        return amount_cents - gst, gst
    return amount_cents, round_cents(Decimal(amount_cents) * rate)


def claimable_itc(gst_cents: int, account_code: str) -> int:
    share = ITC_LIMITED_ACCOUNTS.get(account_code, Decimal(1))
    return round_cents(Decimal(gst_cents) * share)


def gst_return(db: Session, start: date, end: date) -> dict:
    """Working figures for GST34 lines 101, 105, 108, 109 over a reporting period.

    Remittance entries are excluded so paying the balance doesn't net the period to zero.
    """
    moves = account_movements(db, start, end, exclude_sources=("gst_remittance",))
    accounts = accounts_by_code(db)
    sales = sum(c - d for code, (d, c) in moves.items() if accounts[code].type == "revenue")
    collected_d, collected_c = moves.get(coa.GST_COLLECTED, (0, 0))
    itc_d, itc_c = moves.get(coa.GST_ITC, (0, 0))
    line_105 = collected_c - collected_d
    line_108 = itc_d - itc_c
    line_109 = line_105 - line_108
    return {
        "start": start,
        "end": end,
        "line_101_sales": sales,
        "line_105_gst_collected": line_105,
        "line_108_itcs": line_108,
        "line_109_net_tax": line_109,
        "result": "owing" if line_109 > 0 else "refund" if line_109 < 0 else "nil",
        "note": "Line 101 is total revenue including zero-rated and exempt supplies; review before filing.",
    }
