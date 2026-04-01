"""
conftest.py — session-wide fixtures to prevent sys.modules pollution.

Any test that mutates live module attributes (e.g. setting
sys.modules["reasoning_utils"].generate_reasoning = None) will corrupt later
tests that import the same module. This autouse fixture saves and restores
any attributes touched on the reasoning_utils module around every test.
"""
import sys
import pytest


@pytest.fixture(autouse=True)
def _restore_reasoning_utils():
    """Restore reasoning_utils.generate_reasoning after each test."""
    mod = sys.modules.get("reasoning_utils")
    original = getattr(mod, "generate_reasoning", None) if mod else None
    yield
    mod_after = sys.modules.get("reasoning_utils")
    if mod_after is not None and original is not None:
        mod_after.generate_reasoning = original
