# Alberta Books: small-business accounting with an AI assistant

Accounting software for a small incorporated business in **Alberta, Canada**. A
conventional double-entry backend keeps the books exact. Claude sits beside it
to read receipts, categorize bank lines, draft journal entries and answer
questions about the numbers. The AI only ever **suggests**: every draft goes
back through the ledger's validation, and a person posts it.

```
                ┌─────────────── FastAPI (app/main.py) ───────────────┐
 Browser UI ──▶ │  invoices · bills · bank feed · payroll · GST · tax │
 (static/)      └──────┬──────────────────────────────┬───────────────┘
                       │                              │
             deterministic core                  AI layer (app/ai/)
       ledger.py: balanced entries,          rules.py: keyword categorizer (always on)
       integer cents, statements             claude.py: Claude for the lines rules
       tax/: GST, payroll, corporate               can't place, receipts, drafts, Q&A
                       │                              │
                       └──────────▶ SQLite / Postgres ◀┘  (SQLAlchemy)
```

## What it does

| Area | Details |
|---|---|
| **Ledger** | Double-entry journal; every entry must balance to the cent (amounts stored as integer cents). Default chart of accounts for an Alberta CCPC. |
| **Sales** | Customers, invoices with 5% GST (per-line exempt / zero-rated), payments, aged receivables. |
| **Purchases** | Bills paid by cheque, credit card or on account. GST is split out as an input tax credit (ITC), and only **50% of the GST on meals & entertainment** is claimable. |
| **Bank feed** | Import CSV lines. Keyword rules categorize first; only the lines they can't place go to Claude in one batched call. You review, then post. |
| **Payroll** | 2026 CPP (5.95%), CPP2 (4% between YMPE $74,600 and YAMPE $85,000), EI (1.63%, employer 1.4×), and federal and Alberta income tax, following CRA's T4127 method, with year-to-date maximums. Posts wages, employer costs, net pay and the CRA remittance liability. |
| **GST return** | GST34 working figures (lines 101 / 105 / 108 / 109) for any period, plus a "record remittance" entry that clears the GST accounts. |
| **Corporate tax** | Estimate for an Alberta CCPC: 9% federal + 2% Alberta on the first $500k (small business deduction), 15% + 8% above that, with the 50% meals add-back. |
| **Reports** | Income statement, balance sheet (with a balance check), trial balance. |
| **AI assistant** | *Describe a transaction* in plain English, or *upload a receipt* (image or PDF), and get a balanced draft entry. *Ask about your books* answers from a live snapshot of your statements. |

## Run it

```bash
cd accounting
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=sk-ant-...      # optional: without it the app runs rules-only
uvicorn app.main:app --reload
# open http://localhost:8000 · API docs at http://localhost:8000/api/docs
```

Run the tests with `pytest`. They use a fake AI, so they never call the network.

### Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ACCOUNTING_DB_URL` | `sqlite:///./accounting.db` | Any SQLAlchemy URL. Use Postgres in production. |
| `ACCOUNTING_API_KEY` | *(empty)* | When set, every `/api` call must send `X-API-Key`. Set this before exposing the app beyond your machine. |
| `ANTHROPIC_API_KEY` | — | Claude credentials. |
| `ACCOUNTING_CLAUDE_MODEL` | `claude-opus-5-5` | Model used by the AI layer. |
| `ACCOUNTING_AI_ENABLED` | `1` | `0` turns every AI feature off (bank import falls back to rules). |
| `ACCOUNTING_BUSINESS_NAME`, `ACCOUNTING_GST_NUMBER` | — | Shown in the header. |

## How the AI and the backend split the work

* **The backend owns correctness.** Posting, GST maths, payroll and tax are
  deterministic Python. Claude never writes to the database.
* **Rules first, AI second.** `app/ai/rules.py` matches vendor keywords
  (Petro-Canada → Vehicle & Fuel, ENMAX → Utilities, Tim Hortons → Meals, …).
  Only low-confidence lines are sent to Claude, so cost stays low and the
  common cases are instant.
* **Structured output.** Drafts come back as a typed schema
  (`DraftEntry`, `CategorizedBatch`). The server then runs them through
  `ledger.validate_lines`, and the UI shows a draft that doesn't balance or
  names an unknown account as "can't post".
* **Fails safe.** If Claude is unreachable or not configured, the bank import
  still works with rule suggestions and says why. The drafting and Q&A endpoints
  return 503.
* **Alberta context in the prompt.** The system prompt states the rules Claude
  must apply: 5% GST, no PST, 50% meal ITCs, and which items carry no GST.
  The prompt also includes your chart of accounts.

## API overview

All request bodies take dollar amounts (`"125.50"`); **every amount in a
response is integer cents**.

```
GET  /api/accounts                 POST /api/accounts
GET  /api/journal                  POST /api/journal
GET  /api/contacts                 POST /api/contacts
GET  /api/invoices                 POST /api/invoices        POST /api/invoices/{id}/payments
GET  /api/bills                    POST /api/bills
POST /api/bank/import              GET  /api/bank/transactions   POST /api/bank/transactions/{id}/post
GET  /api/employees                POST /api/employees
POST /api/payroll/preview          POST /api/payroll/run      GET  /api/payroll/stubs
GET  /api/reports/trial-balance | income-statement | balance-sheet | aged-receivables
GET  /api/tax/gst-return           POST /api/tax/gst-remit    GET  /api/tax/corporate-estimate
POST /api/ai/draft-entry           POST /api/ai/receipt (multipart)   POST /api/ai/ask
```

## Keeping tax rates current

All rates live in one table, `app/tax/rates.py`, keyed by year. Each January,
add the new year's entry from CRA's *T4127 Payroll Deductions Formulas* and
Alberta's indexed brackets. For a year that has no entry, the app uses the
latest table and reports which year it used (`rates_year`).

## Limitations

This is a working foundation, not a certified payroll or tax product.

* Payroll covers regular salary only. It does not handle bonuses, commissions,
  taxable benefits, RPP or union dues, vacation pay, or the Alberta supplemental
  credit. Check results against CRA's PDOC before remitting.
* The corporate estimate ignores CCA schedules, passive-income and
  taxable-capital grinds, and instalment timing.
* GST line 101 is total revenue. Review exempt and zero-rated supplies before
  filing, and the Quick Method is not modelled.
* The app has no year-end close, multi-currency, bank reconciliation against
  statements, user accounts or audit log yet.

Have a CPA review your setup before you rely on the app for filings.
