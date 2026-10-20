"""Default chart of accounts for a small Alberta corporation (GST registrant, no PST)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account

CASH = "1000"
ACCOUNTS_RECEIVABLE = "1100"
GST_ITC = "1300"
ACCOUNTS_PAYABLE = "2000"
CREDIT_CARD = "2100"
GST_COLLECTED = "2200"
PAYROLL_REMITTANCES = "2300"
CORPORATE_TAX_PAYABLE = "2400"
RETAINED_EARNINGS = "3100"
MEALS = "6150"
WAGES = "6700"
EMPLOYER_PAYROLL_TAXES = "6710"

# (code, name, type, keywords)
DEFAULT_ACCOUNTS = [
    ("1000", "Cash - Chequing", "asset", "bank, chequing"),
    ("1010", "Cash - Savings", "asset", "savings, transfer to savings"),
    ("1100", "Accounts Receivable", "asset", ""),
    ("1200", "Inventory", "asset", "inventory, stock purchase"),
    ("1300", "GST Paid on Purchases (ITC)", "asset", ""),
    ("1400", "Prepaid Expenses", "asset", "prepaid"),
    ("1500", "Equipment & Computers", "asset", "laptop, computer, equipment, best buy, apple store, dell"),
    ("1510", "Accumulated Depreciation", "asset", ""),
    ("1600", "Vehicles", "asset", "vehicle purchase, truck purchase"),
    ("2000", "Accounts Payable", "liability", ""),
    ("2100", "Credit Card Payable", "liability", "visa payment, mastercard payment, amex payment"),
    ("2200", "GST Collected", "liability", ""),
    ("2300", "Payroll Remittances Payable", "liability", "cra source deductions, payroll remittance"),
    ("2400", "Corporate Income Tax Payable", "liability", "corporate tax instalment"),
    ("2500", "Shareholder Loan", "liability", "shareholder, owner draw"),
    ("2600", "Bank Loan", "liability", "loan payment"),
    ("3000", "Share Capital", "equity", ""),
    ("3100", "Retained Earnings", "equity", ""),
    ("3200", "Dividends Declared", "equity", "dividend"),
    ("4000", "Sales Revenue", "revenue", "sale, square deposit, shopify payout, stripe payout"),
    ("4100", "Service Revenue", "revenue", "consulting income, service fee received, e-transfer received"),
    ("4900", "Other Income", "revenue", "interest earned, interest income, rebate"),
    ("5000", "Cost of Goods Sold", "expense", "wholesale, supplier, materials"),
    ("6000", "Advertising & Marketing", "expense", "google ads, facebook, meta ads, advertising, marketing, linkedin ads"),
    ("6100", "Bank Fees & Interest", "expense", "service charge, monthly fee, nsf, interest charge, bank fee"),
    ("6150", "Meals & Entertainment", "expense", "restaurant, tim hortons, starbucks, cafe, coffee, pub, skip the dishes, doordash"),
    ("6200", "Office Supplies", "expense", "staples, office depot, paper, toner, supplies"),
    ("6250", "Software & Subscriptions", "expense", "microsoft, google workspace, adobe, quickbooks, saas, subscription, zoom, slack, github, aws"),
    ("6300", "Professional Fees", "expense", "accountant, legal, lawyer, bookkeeping, cpa"),
    ("6350", "Rent", "expense", "rent, lease"),
    ("6400", "Utilities", "expense", "enmax, epcor, atco, direct energy, utilities, power, gas bill"),
    ("6450", "Telephone & Internet", "expense", "telus, shaw, rogers, bell, koodo, internet, phone, mobile"),
    ("6500", "Vehicle & Fuel", "expense", "petro-canada, shell, esso, co-op gas, fuel, gas station, parking, impark"),
    ("6550", "Travel", "expense", "westjet, air canada, flair, hotel, airbnb, uber, taxi"),
    ("6600", "Insurance", "expense", "insurance, intact, aviva"),
    ("6700", "Wages & Salaries", "expense", "payroll, wages"),
    ("6710", "Employer Payroll Costs (CPP/EI)", "expense", ""),
    ("6800", "Repairs & Maintenance", "expense", "repair, maintenance, home depot, rona"),
    ("6850", "Licences, Dues & Memberships", "expense", "licence, permit, membership, dues, city of calgary, city of edmonton, corporate registry"),
    ("6900", "Depreciation (CCA)", "expense", ""),
    ("6950", "Income Tax Expense", "expense", ""),
    ("6990", "Miscellaneous Expense", "expense", ""),
]


def seed_accounts(db: Session) -> int:
    existing = set(db.scalars(select(Account.code)))
    added = 0
    for code, name, type_, keywords in DEFAULT_ACCOUNTS:
        if code not in existing:
            db.add(Account(code=code, name=name, type=type_, keywords=keywords))
            added += 1
    db.commit()
    return added
