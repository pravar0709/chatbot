"""Root conftest – sets environment BEFORE any app module is imported."""
import os
import tempfile

# Suppress litellm network calls
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["LITELLM_LOG"] = "ERROR"

# Test-specific config
_tmp = tempfile.mkdtemp()
os.environ.setdefault("LLM_API_KEYS", "fake-key-1,fake-key-2")
os.environ.setdefault("LLM_MODEL", "gemini/gemini-2.0-flash")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(_tmp, 'test.db')}")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ENABLE_FAILURE_SIMULATION", "true")
os.environ.setdefault("DEFAULT_SYSTEM_PROMPT", "You are a helpful assistant.")
