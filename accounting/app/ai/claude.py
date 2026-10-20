"""Claude-backed features: bank categorization, journal-entry drafting (text or receipt image)
and Q&A over the books. The AI only ever *suggests*: every draft goes back through the
ledger's validation and is posted only when a user approves it."""
import base64
import json
from datetime import date

import anthropic
from pydantic import BaseModel, Field

from app import config
from app.models import Account

FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_BASE = (
    "You are the bookkeeping assistant inside an accounting system for a small incorporated "
    "business in Alberta, Canada. Context you must apply: Alberta has 5% GST and no PST or HST; "
    "a GST registrant claims input tax credits (ITCs) on business purchases, but only 50% of the GST "
    "on meals and entertainment; bank fees, insurance premiums, wages, payroll remittances, loan "
    "principal and transfers carry no GST. The fiscal records use Canadian dollars. Use only "
    "account codes from the chart of accounts provided. If something is ambiguous, pick the "
    "most likely treatment and say what a human should check, rather than inventing facts."
)


class AIUnavailable(RuntimeError):
    pass


class CategorizedTxn(BaseModel):
    index: int
    account_code: str
    gst_included: bool = Field(description="True if the amount likely includes 5% GST that is claimable")
    confidence: str = Field(description="high, medium or low")
    reason: str


class CategorizedBatch(BaseModel):
    results: list[CategorizedTxn]


class DraftLine(BaseModel):
    account_code: str
    debit: float = Field(description="Dollars, 0 if this is a credit line")
    credit: float = Field(description="Dollars, 0 if this is a debit line")
    description: str


class DraftEntry(BaseModel):
    date: str = Field(description="ISO date YYYY-MM-DD")
    memo: str
    lines: list[DraftLine]
    explanation: str = Field(description="One or two sentences on the treatment chosen")
    review_notes: list[str] = Field(description="Things a human should verify; empty if none")


def chart_text(accounts: list[Account]) -> str:
    return "\n".join(f"{a.code} {a.name} ({a.type})" for a in accounts if a.is_active)


class ClaudeService:
    def __init__(self, model: str = config.CLAUDE_MODEL, client: anthropic.Anthropic | None = None):
        self.model = model
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _system(self, accounts: list[Account]) -> list[dict]:
        return [
            {"type": "text", "text": SYSTEM_BASE},
            {"type": "text", "text": "Chart of accounts:\n" + chart_text(accounts)},
        ]

    def _call(self, *, accounts, content, effort: str, output_format=None, max_tokens: int = 16000):
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=self._system(accounts),
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort},
            # On a safety decline, the API re-runs the request on a fallback model it picks.
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        try:
            if output_format is None:
                response = self.client.beta.messages.create(**kwargs)
            else:
                response = self.client.beta.messages.parse(output_format=output_format, **kwargs)
        except anthropic.AuthenticationError as e:
            raise AIUnavailable("Claude credentials are missing or invalid; set ANTHROPIC_API_KEY") from e
        except anthropic.RateLimitError as e:
            raise AIUnavailable("Claude is rate limited; try again shortly") from e
        except anthropic.APIStatusError as e:
            raise AIUnavailable(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AIUnavailable("Could not reach the Claude API") from e
        except TypeError as e:
            # The SDK raises TypeError before sending when no credential source resolves.
            if "authentication" not in str(e):
                raise
            raise AIUnavailable("No Claude credentials configured; set ANTHROPIC_API_KEY") from e

        if response.stop_reason == "refusal":
            raise AIUnavailable("Claude declined this request")
        if response.stop_reason == "max_tokens":
            raise AIUnavailable("Claude's response was cut off; try a shorter request")
        if output_format is not None:
            if response.parsed_output is None:
                raise AIUnavailable("Claude returned output that did not match the expected format")
            return response.parsed_output
        return "".join(b.text for b in response.content if b.type == "text")

    def categorize(self, txns: list[dict], accounts: list[Account]) -> list[CategorizedTxn]:
        """txns: [{index, date, description, amount}] where amount is dollars, negative = money out."""
        prompt = (
            "Categorize each bank transaction to one account code. Negative amounts are money "
            "leaving the business bank account; positive amounts are deposits. Return one result "
            "per input index.\n\n" + json.dumps(txns, default=str)
        )
        batch = self._call(accounts=accounts, content=prompt, effort="low", output_format=CategorizedBatch)
        return batch.results

    def draft_entry(
        self,
        accounts: list[Account],
        text: str = "",
        image: bytes | None = None,
        media_type: str = "image/jpeg",
        today: date | None = None,
    ) -> DraftEntry:
        content: list[dict] = []
        if image:
            if media_type == "application/pdf":
                source_block = {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()}}
            else:
                source_block = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()}}
            content.append(source_block)
        content.append(
            {
                "type": "text",
                "text": (
                    f"Today is {(today or date.today()).isoformat()}. Draft one balanced double-entry "
                    "journal entry for the transaction below"
                    + (" (the attached receipt/invoice is the source document)" if image else "")
                    + ". Split out GST to account 1300 when it is claimable (50% for meals; the "
                    "unclaimable half stays in the expense). If the payment method isn't stated, "
                    "credit 1000 Cash - Chequing and note it. Total debits must equal total credits "
                    "to the cent.\n\n"
                    + (text or "(see attachment)")
                ),
            }
        )
        return self._call(accounts=accounts, content=content, effort="medium", output_format=DraftEntry)

    def ask(self, question: str, snapshot: dict, accounts: list[Account]) -> str:
        content = (
            "Here is a snapshot of the business's books (amounts in cents, as integers):\n"
            + json.dumps(snapshot, default=str)
            + "\n\nAnswer the owner's question using these figures. Be concise, show the numbers "
            "you relied on in dollars, and flag anything that needs an accountant (CPA) to confirm. "
            "You are not giving formal tax or legal advice.\n\nQuestion: "
            + question
        )
        return self._call(accounts=accounts, content=content, effort="medium")


_service = ClaudeService()


def get_ai() -> ClaudeService | None:
    return _service if config.AI_ENABLED else None
