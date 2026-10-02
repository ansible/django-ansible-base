"""Shared fixtures for lib/ serializer and validation signal tests."""

import pytest

from ansible_base.lib.utils import validation_signals


@pytest.fixture
def restore_protected_models_registry():
    """Snapshot ``_protected_models`` so dynamic serializer tests do not leak registry state."""
    snapshot = validation_signals._protected_models.copy()
    yield
    validation_signals._protected_models.clear()
    validation_signals._protected_models.update(snapshot)
