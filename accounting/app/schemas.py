"""Request bodies. Money comes in as Decimal dollars and is stored as cents."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class AccountIn(BaseModel):
    code: str = Field(pattern=r"^\d{4}$")
    name: str
    type: str = Field(pattern="^(asset|liability|equity|revenue|expense)$")
    keywords: str = ""


class LineIn(BaseModel):
    account_code: str
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    description: str = ""


class JournalEntryIn(BaseModel):
    date: date
    memo: str = ""
    lines: list[LineIn]
    source: str = "manual"


class ContactIn(BaseModel):
    name: str
    kind: str = Field(pattern="^(customer|vendor)$")
    email: str = ""
    gst_number: str = ""


class InvoiceLineIn(BaseModel):
    description: str
    quantity: Decimal = Decimal(1)
    unit_price: Decimal
    account_code: str = "4100"
    gst_exempt: bool = False


class InvoiceIn(BaseModel):
    customer_id: int
    issue_date: date
    due_days: int = 30
    lines: list[InvoiceLineIn] = Field(min_length=1)


class PaymentIn(BaseModel):
    date: date
    deposit_to: str = "1000"


class BillIn(BaseModel):
    vendor_name: str
    vendor_id: int | None = None
    date: date
    description: str
    account_code: str
    amount: Decimal
    gst_included: bool = True
    gst_exempt: bool = False
    paid_from: str = "2000"  # 2000 = on account (AP), 1000 = bank, 2100 = credit card


class BankTxnIn(BaseModel):
    date: date
    description: str
    amount: Decimal  # negative = withdrawal


class BankImportIn(BaseModel):
    bank_account_code: str = "1000"
    transactions: list[BankTxnIn]
    use_ai: bool = True


class BankPostIn(BaseModel):
    account_code: str | None = None  # defaults to the suggestion
    gst_included: bool | None = None


class EmployeeIn(BaseModel):
    name: str
    pay_periods: int = Field(26, description="52 weekly, 26 bi-weekly, 24 semi-monthly, 12 monthly")
    gross_per_period: Decimal
    federal_claim: Decimal | None = None
    alberta_claim: Decimal | None = None


class PayRunIn(BaseModel):
    pay_date: date
    employee_ids: list[int] | None = None  # None = everyone


class PayrollPreviewIn(BaseModel):
    gross: Decimal
    pay_periods: int = 26
    year: int = 2026


class GstRemitIn(BaseModel):
    start: date
    end: date
    paid_on: date
    paid_from: str = "1000"


class DraftIn(BaseModel):
    text: str


class AskIn(BaseModel):
    question: str
    start: date | None = None
    end: date | None = None
