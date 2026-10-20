"""Corporate income tax estimate for an Alberta CCPC."""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app import chart_of_accounts as coa
from app.ledger import account_movements, income_statement
from app.money import round_cents
from app.tax.rates import rates_for, rates_year

# Only 50% of meals and entertainment is deductible (ITA s.67.1).
MEALS_DEDUCTIBLE = Decimal("0.5")


def estimate(db: Session, start: date, end: date, small_business_limit_share: Decimal = Decimal(1)) -> dict:
    """Estimate federal + Alberta tax on the period's book income.

    `small_business_limit_share` covers associated corporations that share the
    $500k business limit. Book depreciation is used as a stand-in for CCA, and
    income tax expense itself is added back.
    """
    r = rates_for(end.year)
    pnl = income_statement(db, start, end)
    moves = account_movements(db, start, end)
    meals_d, meals_c = moves.get(coa.MEALS, (0, 0))
    tax_d, tax_c = moves.get("6950", (0, 0))
    meals_addback = round_cents(Decimal(meals_d - meals_c) * (1 - MEALS_DEDUCTIBLE))
    taxable = max(0, pnl["net_income"] + meals_addback + (tax_d - tax_c))

    limit = round_cents(r.small_business_limit * small_business_limit_share * 100)
    small = min(taxable, limit)
    general = taxable - small
    federal = round_cents(small * r.federal_small_business_rate + general * r.federal_general_rate)
    alberta = round_cents(small * r.alberta_small_business_rate + general * r.alberta_general_rate)
    return {
        "start": start,
        "end": end,
        "rates_year": rates_year(end.year),
        "book_net_income": pnl["net_income"],
        "meals_addback": meals_addback,
        "income_tax_expense_addback": tax_d - tax_c,
        "taxable_income": taxable,
        "small_business_portion": small,
        "general_portion": general,
        "federal_tax": federal,
        "alberta_tax": alberta,
        "total_tax": federal + alberta,
        "effective_rate": round(float((federal + alberta) / taxable), 4) if taxable else 0.0,
        "note": "Estimate only: assumes a CCPC with active business income, no CCA schedule, "
        "no passive-income grind and no taxable-capital grind.",
    }
