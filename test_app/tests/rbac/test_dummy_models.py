"""Test dummy models for optional django-ansible-base apps."""

import pytest

from ansible_base.rbac.models.dummy_models import DummyAuditableModel


class TestDummyModel(DummyAuditableModel):
    """Test model using DummyAuditableModel for testing."""

    class Meta:
        app_label = 'test_app'


@pytest.mark.django_db
def test_dummy_auditable_model_interface():
    """Test that DummyAuditableModel provides expected interface without crashing."""
    # Create test instance
    test_obj = TestDummyModel()

    # Test activity_stream_entries property
    entries = test_obj.activity_stream_entries
    assert entries.count() == 0, "Dummy model should return empty count"
    assert entries.last() is None, "Dummy model should return None for last()"
    assert list(entries) == [], "Dummy model should return empty list"
    assert entries.all() == entries, "all() should return self"
    assert entries.order_by('id') == entries, "order_by() should return self"

    # Test class attributes
    assert hasattr(test_obj, 'activity_stream_excluded_field_names')
    assert test_obj.activity_stream_excluded_field_names == []
    assert hasattr(test_obj, 'activity_stream_limit_field_names')
    assert test_obj.activity_stream_limit_field_names == []

    # Test extra_related_fields method
    assert test_obj.extra_related_fields(None) == {}


def test_dummy_model_import_safety():
    """Test that DummyAuditableModel can be imported safely."""
    # The main purpose is that this import doesn't crash AWX/EDA
    from ansible_base.rbac.models.dummy_models import DummyAuditableModel

    # Basic verification that it's properly configured
    assert DummyAuditableModel._meta.abstract is True
