"""Runtime settings, read from the environment once at import."""
import os

DATABASE_URL = os.environ.get("ACCOUNTING_DB_URL", "sqlite:///./accounting.db")

# Optional shared secret. When set, every /api request must send it as X-API-Key.
API_KEY = os.environ.get("ACCOUNTING_API_KEY", "")

# The AI layer is optional: without credentials the app falls back to its
# rule-based categorizer and the /api/ai/* drafting endpoints return 503.
CLAUDE_MODEL = os.environ.get("ACCOUNTING_CLAUDE_MODEL", "claude-opus-5-5")
AI_ENABLED = os.environ.get("ACCOUNTING_AI_ENABLED", "1") == "1"

BUSINESS_NAME = os.environ.get("ACCOUNTING_BUSINESS_NAME", "My Alberta Business Ltd.")
GST_NUMBER = os.environ.get("ACCOUNTING_GST_NUMBER", "")
