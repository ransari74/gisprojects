"""Per-period payroll deductions for an Alberta employee.

Follows the shape of CRA's T4127 (annualise the period, apply brackets and
non-refundable credits, de-annualise), simplified: no RPP/union dues/other
deductions, no commission or bonus methods, no Alberta supplemental credit
(which only applies when credit claims exceed $60,000). Treat results as an
estimate and check against CRA's PDOC before remitting.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal

from app.money import round_cents
from app.tax.rates import bracket_tax, rates_for, rates_year

D = Decimal


@dataclass
class YearToDate:
    gross: int = 0  # cents, pensionable earnings so far this year
    cpp: int = 0
    cpp2: int = 0
    ei: int = 0


@dataclass
class Deductions:
    rates_year: int
    gross: int
    cpp: int
    cpp2: int
    ei: int
    federal_tax: int
    alberta_tax: int
    net: int
    employer_cpp: int
    employer_cpp2: int
    employer_ei: int

    @property
    def employee_total(self) -> int:
        return self.cpp + self.cpp2 + self.ei + self.federal_tax + self.alberta_tax

    @property
    def employer_total(self) -> int:
        return self.employer_cpp + self.employer_cpp2 + self.employer_ei

    def as_dict(self) -> dict:
        return asdict(self) | {"employee_total": self.employee_total, "employer_total": self.employer_total}


def _federal_bpa(r, annual_income: Decimal) -> Decimal:
    if annual_income <= r.federal_bpa_phaseout_start:
        return r.federal_bpa_max
    if annual_income >= r.federal_bpa_phaseout_end:
        return r.federal_bpa_min
    span = r.federal_bpa_phaseout_end - r.federal_bpa_phaseout_start
    reduction = (r.federal_bpa_max - r.federal_bpa_min) * (annual_income - r.federal_bpa_phaseout_start) / span
    return r.federal_bpa_max - reduction


def calculate(
    gross_cents: int,
    pay_periods: int,
    year: int,
    ytd: YearToDate | None = None,
    federal_claim_cents: int | None = None,
    alberta_claim_cents: int | None = None,
) -> Deductions:
    r = rates_for(year)
    ytd = ytd or YearToDate()
    P = D(pay_periods)
    gross = D(gross_cents) / 100

    # CPP: per-period exemption, capped at the annual maximum.
    cpp = max(D(0), gross - r.cpp_basic_exemption / P) * r.cpp_rate
    cpp = min(cpp, r.cpp_max - D(ytd.cpp) / 100)

    # CPP2: only on the slice of year-to-date earnings between YMPE and YAMPE.
    before = D(ytd.gross) / 100
    after = before + gross
    band = max(D(0), min(after, r.cpp_yampe) - max(before, r.cpp_ympe))
    cpp2 = min(band * r.cpp2_rate, r.cpp2_max - D(ytd.cpp2) / 100)

    ei = min(gross * r.ei_rate, r.ei_max - D(ytd.ei) / 100)

    cpp, cpp2, ei = (max(D(0), x).quantize(D("0.01")) for x in (cpp, cpp2, ei))

    # Enhanced CPP (the part above the base rate) and all of CPP2 are deductions from income;
    # the base part is a non-refundable credit.
    cpp_enhanced = cpp * (r.cpp_rate - r.cpp_base_rate) / r.cpp_rate
    cpp_base = cpp - cpp_enhanced
    annual_income = max(D(0), P * (gross - cpp_enhanced - cpp2))

    annual_cpp_credit = min(P * cpp_base, r.cpp_max * r.cpp_base_rate / r.cpp_rate)
    annual_ei_credit = min(P * ei, r.ei_max)

    fed_low = r.federal_brackets[0].rate
    fed_claim = D(federal_claim_cents) / 100 if federal_claim_cents is not None else _federal_bpa(r, annual_income)
    fed_credits = fed_low * (fed_claim + annual_cpp_credit + annual_ei_credit + min(r.canada_employment_amount, annual_income))
    federal = max(D(0), bracket_tax(annual_income, r.federal_brackets) - fed_credits) / P

    ab_low = r.alberta_brackets[0].rate
    ab_claim = D(alberta_claim_cents) / 100 if alberta_claim_cents is not None else r.alberta_bpa
    ab_credits = ab_low * (ab_claim + annual_cpp_credit + annual_ei_credit)
    alberta = max(D(0), bracket_tax(annual_income, r.alberta_brackets) - ab_credits) / P

    c = lambda x: round_cents(x * 100)  # noqa: E731
    cpp_c, cpp2_c, ei_c, fed_c, ab_c = c(cpp), c(cpp2), c(ei), c(federal), c(alberta)
    return Deductions(
        rates_year=rates_year(year),
        gross=gross_cents,
        cpp=cpp_c,
        cpp2=cpp2_c,
        ei=ei_c,
        federal_tax=fed_c,
        alberta_tax=ab_c,
        net=gross_cents - cpp_c - cpp2_c - ei_c - fed_c - ab_c,
        employer_cpp=cpp_c,
        employer_cpp2=cpp2_c,
        employer_ei=c(ei * r.ei_employer_multiplier),
    )
