from decimal import Decimal

from app.tax import gst, payroll
from app.tax.rates import RATES, bracket_tax


def test_gst_split_included_and_excluded():
    assert gst.split_gst(10500, gst_included=True, year=2026) == (10000, 500)
    assert gst.split_gst(10000, gst_included=False, year=2026) == (10000, 500)
    assert gst.split_gst(10000, gst_included=False, year=2026, exempt=True) == (10000, 0)


def test_meals_itc_is_half():
    assert gst.claimable_itc(500, "6150") == 250
    assert gst.claimable_itc(500, "6200") == 500


def test_bracket_tax_alberta():
    b = RATES[2026].alberta_brackets
    assert bracket_tax(Decimal("50000"), b) == Decimal("4000.00")
    # 61,200 at 8% + 8,800 at 10%
    assert bracket_tax(Decimal("70000"), b) == Decimal("61200") * Decimal("0.08") + Decimal("8800") * Decimal("0.10")


def test_payroll_biweekly_52k():
    d = payroll.calculate(200000, 26, 2026)
    # CPP: (2000 - 3500/26) * 5.95% = 110.99 ; EI: 2000 * 1.63% = 32.60
    assert d.cpp == 11099
    assert d.ei == 3260
    assert d.cpp2 == 0
    assert d.employer_ei == round(3260 * 1.4)
    assert 15000 < d.federal_tax < 17500
    assert 7000 < d.alberta_tax < 8500
    assert d.net == d.gross - d.employee_total


def test_payroll_respects_annual_maximums():
    r = RATES[2026]
    ytd = payroll.YearToDate(gross=8_000_000, cpp=int(r.cpp_max * 100), cpp2=0, ei=int(r.ei_max * 100))
    d = payroll.calculate(500000, 26, 2026, ytd=ytd)
    assert d.cpp == 0 and d.ei == 0
    # 80,000 -> 85,000 is inside the CPP2 band: 5,000 * 4%
    assert d.cpp2 == 20000


def test_low_income_has_no_tax():
    d = payroll.calculate(30000, 26, 2026)  # $7,800/yr
    assert d.federal_tax == 0 and d.alberta_tax == 0
