import os
import sys

import pytest

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(autouse=True)
def _disable_langfuse(monkeypatch):
    """Tests must never send traces to a real Langfuse project, even when
    LANGFUSE_* keys are present in the local .env for manual runs."""
    import observability

    monkeypatch.setattr(observability, "_enabled", False)
    monkeypatch.setattr(observability, "_client", None)
