"""Shared test setup."""
import os

# A developer's .env must never make the test suite post to a real chat channel.
# Set before shared.config is imported; load_dotenv does not override existing variables.
os.environ["WEBHOOK_URL"] = ""
# Tests never call a real LLM: no Gemini key either (Claude keys are blanked per test).
os.environ["GEMINI_API_KEY"] = ""
