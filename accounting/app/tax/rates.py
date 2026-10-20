"""Tax parameters for an Alberta business, keyed by year.

Figures for 2026 come from CRA's T4032/T4127 payroll guidance and Alberta's
indexed brackets. Verify every January against CRA's "Payroll Deductions
Formulas" (T4127) and add the next year's entry before running payroll in it.
"""
from dataclasses import dataclass
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class Bracket:
    up_to: Decimal | None  # None = no upper limit
    rate: Decimal


@dataclass(frozen=True)
class YearRates:
    # GST (Alberta has no PST or HST)
    gst_rate: Decimal
    small_supplier_threshold: Decimal

    # CPP / CPP2
    cpp_basic_exemption: Decimal
    cpp_ympe: Decimal
    cpp_yampe: Decimal
    cpp_rate: Decimal  # employee and employer each
    cpp_base_rate: Decimal  # portion of cpp_rate that earns a credit; the rest is a deduction
    cpp2_rate: Decimal

    # EI
    ei_max_insurable: Decimal
    ei_rate: Decimal
    ei_employer_multiplier: Decimal

    # Personal income tax
    federal_brackets: tuple[Bracket, ...]
    federal_bpa_max: Decimal
    federal_bpa_min: Decimal
    federal_bpa_phaseout_start: Decimal
    federal_bpa_phaseout_end: Decimal
    canada_employment_amount: Decimal
    alberta_brackets: tuple[Bracket, ...]
    alberta_bpa: Decimal

    # Corporate income tax (Canadian-controlled private corporation)
    small_business_limit: Decimal
    federal_small_business_rate: Decimal
    federal_general_rate: Decimal
    alberta_small_business_rate: Decimal
    alberta_general_rate: Decimal

    @property
    def cpp_max(self) -> Decimal:
        return ((self.cpp_ympe - self.cpp_basic_exemption) * self.cpp_rate).quantize(D("0.01"))

    @property
    def cpp2_max(self) -> Decimal:
        return ((self.cpp_yampe - self.cpp_ympe) * self.cpp2_rate).quantize(D("0.01"))

    @property
    def ei_max(self) -> Decimal:
        return (self.ei_max_insurable * self.ei_rate).quantize(D("0.01"))


RATES: dict[int, YearRates] = {
    2026: YearRates(
        gst_rate=D("0.05"),
        small_supplier_threshold=D("30000"),
        cpp_basic_exemption=D("3500"),
        cpp_ympe=D("74600"),
        cpp_yampe=D("85000"),
        cpp_rate=D("0.0595"),
        cpp_base_rate=D("0.0495"),
        cpp2_rate=D("0.04"),
        ei_max_insurable=D("68900"),
        ei_rate=D("0.0163"),
        ei_employer_multiplier=D("1.4"),
        federal_brackets=(
            Bracket(D("58523"), D("0.14")),
            Bracket(D("117045"), D("0.205")),
            Bracket(D("181440"), D("0.26")),
            Bracket(D("258482"), D("0.29")),
            Bracket(None, D("0.33")),
        ),
        federal_bpa_max=D("16452"),
        federal_bpa_min=D("14829"),
        federal_bpa_phaseout_start=D("181440"),
        federal_bpa_phaseout_end=D("258482"),
        canada_employment_amount=D("1501"),
        alberta_brackets=(
            Bracket(D("61200"), D("0.08")),
            Bracket(D("154259"), D("0.10")),
            Bracket(D("185111"), D("0.12")),
            Bracket(D("246813"), D("0.13")),
            Bracket(D("370220"), D("0.14")),
            Bracket(None, D("0.15")),
        ),
        alberta_bpa=D("22769"),
        small_business_limit=D("500000"),
        federal_small_business_rate=D("0.09"),
        federal_general_rate=D("0.15"),
        alberta_small_business_rate=D("0.02"),
        alberta_general_rate=D("0.08"),
    ),
}


def rates_for(year: int) -> YearRates:
    if year in RATES:
        return RATES[year]
    # Fall back to the latest known year rather than refusing to run; callers
    # surface `rates_year` so the user can see which table was used.
    return RATES[max(RATES)]


def rates_year(year: int) -> int:
    return year if year in RATES else max(RATES)


def bracket_tax(income: Decimal, brackets: tuple[Bracket, ...]) -> Decimal:
    tax, lower = D(0), D(0)
    for b in brackets:
        upper = b.up_to if b.up_to is not None else income
        if income > lower:
            tax += (min(income, upper) - lower) * b.rate
        lower = upper
        if b.up_to is None or income <= upper:
            break
    return tax
