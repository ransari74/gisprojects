"""ORM models. Every money column is an integer number of cents, so sums are exact."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(10))
    # Short hint used by the categorizers, e.g. "staples, paper, toner".
    keywords: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    memo: Mapped[str] = mapped_column(String(255), default="")
    # manual | invoice | invoice_payment | bill | bill_payment | bank | payroll | gst_remittance | ai
    source: Mapped[str] = mapped_column(String(30), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    debit: Mapped[int] = mapped_column(Integer, default=0)
    credit: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String(255), default="")

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    account: Mapped[Account] = relationship(lazy="joined")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))  # customer | vendor
    email: Mapped[str] = mapped_column(String(120), default="")
    gst_number: Mapped[str] = mapped_column(String(20), default="")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    subtotal: Mapped[int] = mapped_column(Integer)
    gst: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | paid
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"))
    payment_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)

    customer: Mapped[Contact] = relationship(lazy="joined")
    lines: Mapped[list["InvoiceLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[str] = mapped_column(String(20))  # decimal kept as text
    unit_price: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    account_code: Mapped[str] = mapped_column(String(10))
    gst_exempt: Mapped[bool] = mapped_column(Boolean, default=False)


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    vendor_name: Mapped[str] = mapped_column(String(120))
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(255))
    account_code: Mapped[str] = mapped_column(String(10))
    subtotal: Mapped[int] = mapped_column(Integer)
    gst: Mapped[int] = mapped_column(Integer)
    itc: Mapped[int] = mapped_column(Integer)  # GST claimable as input tax credit
    total: Mapped[int] = mapped_column(Integer)
    paid_from: Mapped[str] = mapped_column(String(10))  # account code credited
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"))


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_account_code: Mapped[str] = mapped_column(String(10), default="1000")
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column(Integer)  # +deposit / -withdrawal
    suggested_account: Mapped[str] = mapped_column(String(10), default="")
    suggested_gst: Mapped[bool] = mapped_column(Boolean, default=False)
    suggestion_source: Mapped[str] = mapped_column(String(10), default="")  # rules | ai
    suggestion_reason: Mapped[str] = mapped_column(String(255), default="")
    confidence: Mapped[str] = mapped_column(String(10), default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | posted
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    pay_periods: Mapped[int] = mapped_column(Integer, default=26)  # 52, 26, 24, 12
    gross_per_period: Mapped[int] = mapped_column(Integer)
    # TD1 / TD1AB claim codes default to the basic personal amounts.
    federal_claim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alberta_claim: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PayStub(Base):
    __tablename__ = "pay_stubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    pay_date: Mapped[date] = mapped_column(Date)
    gross: Mapped[int] = mapped_column(Integer)
    cpp: Mapped[int] = mapped_column(Integer)
    cpp2: Mapped[int] = mapped_column(Integer)
    ei: Mapped[int] = mapped_column(Integer)
    federal_tax: Mapped[int] = mapped_column(Integer)
    alberta_tax: Mapped[int] = mapped_column(Integer)
    net: Mapped[int] = mapped_column(Integer)
    employer_cpp: Mapped[int] = mapped_column(Integer)
    employer_ei: Mapped[int] = mapped_column(Integer)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"))

    employee: Mapped[Employee] = relationship(lazy="joined")
