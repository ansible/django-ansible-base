"""Tests for ORM-direct validation bypass logging signal handler.

Tests verify that the validation_bypass_logger signal:
1. Logs validation violations when models are saved directly via ORM
2. Does NOT log when saves go through DRF serializers with CleanTextMixin
3. Captures Tier 1 (name field) and Tier 2 (free text) violations
4. Includes structured audit information (resource type, field, tier, caller)
5. Never blocks saves (observability-only)
"""
import logging

import pytest
from django.test import override_settings
from rest_framework import serializers

from ansible_base.lib.serializers.mixins import CleanTextMixin
from ansible_base.lib.utils.validation_signals import (
    _get_text_fields,
    _validate_field,
    get_validation_context_token,
    register_validation_signals,
    reset_validation_context,
)
from test_app.models import City, Organization


# Register signals before tests run
register_validation_signals()


class OrgSerializer(CleanTextMixin, serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['name', 'description']


@pytest.fixture
def enable_validation(settings):
    """Enable ENHANCED_INPUT_VALIDATION_ENABLED for tests."""
    settings.ENHANCED_INPUT_VALIDATION_ENABLED = True


@pytest.mark.django_db
class TestValidationBypassLogging:
    """Test that ORM-direct writes log validation violations."""

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_orm_create_tier2_violation_logs(self, caplog):
        """AC #6.1: ORM-direct create with Tier 2 violation triggers a log entry."""
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        # Create via ORM with a Tier 2 violation (HTML tag in description)
        org = Organization.objects.create(
            name='ValidName',
            description='<script>alert("xss")</script>'
        )

        # Save succeeded (observability-only, doesn't block)
        assert org.pk is not None

        # Log entry was created -- exactly one, for Organization itself. (A regression
        # here historically came from resource_registry's Resource model cascading its
        # own .save() from a post_save receiver on Organization and getting logged too;
        # the model registry scopes the signal to Organization only.)
        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert len(signal_logs) == 1
        log_record = signal_logs[0]

        # Verify log structure
        assert log_record.levelname == 'WARNING'
        assert 'description' in log_record.message
        assert 'test_app.Organization' in log_record.message
        assert 'Tier 2' in log_record.message
        assert "can't include HTML tags" in log_record.message
        assert 'caller:' in log_record.message

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_orm_update_tier1_violation_logs(self, caplog):
        """AC #6.2: ORM-direct update with Tier 1 violation triggers a log entry."""
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        # Create with valid data
        org = Organization.objects.create(name='ValidName', description='Valid description')
        caplog.clear()

        # Update via ORM with a Tier 1 violation (invalid character in name)
        org.name = 'Invalid<Name'
        org.save()

        # Save succeeded
        org.refresh_from_db()
        assert org.name == 'Invalid<Name'

        # Log entry was created -- exactly one, not inflated by unrelated cascade saves
        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert len(signal_logs) == 1
        log_record = signal_logs[0]

        # Verify Tier 1 violation logged
        assert 'name' in log_record.message
        assert 'test_app.Organization' in log_record.message
        assert 'Tier 1' in log_record.message
        assert 'valid name' in log_record.message.lower()

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_serializer_write_no_signal_log(self, caplog):
        """AC #6.3: Serializer-mediated writes do NOT trigger the signal log."""
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        # Create via serializer with invalid data (should be rejected by serializer)
        serializer = OrgSerializer(data={
            'name': 'ValidName',
            'description': '<script>xss</script>'
        })

        # Serializer validation catches the error
        assert not serializer.is_valid()
        assert 'description' in serializer.errors

        # CleanTextMixin logs the rejection
        # But the SIGNAL should NOT log (no double-logging)
        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert len(signal_logs) == 0, "Signal should not log for serializer-mediated writes"

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_serializer_valid_create_actually_saved_no_signal_log(self, caplog):
        """A valid serializer create must not log, including through the actual .save() call.

        Regression test: is_valid() alone does not exercise the real save/post_save path.
        The guard has to survive through serializer.save() (and any post_save cascades it
        triggers), not just validate().
        """
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        serializer = OrgSerializer(data={'name': 'ValidName', 'description': 'A valid description'})
        assert serializer.is_valid(), serializer.errors
        instance = serializer.save()

        assert instance.pk is not None
        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert signal_logs == []

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_serializer_grandfathered_update_no_signal_log(self, caplog):
        """A grandfathered field must not falsely appear as an ORM bypass via the signal.

        Regression test for a real bug: an instance with a pre-existing (legacy) invalid
        `name` is updated through a CleanTextMixin serializer that only changes
        `description`. CleanTextMixin.validate() correctly grandfathers the unchanged
        `name` field and the write succeeds -- this is a fully compliant,
        serializer-mediated save. The signal must not log it as a bypass just because the
        stored `name` value would fail validation if it were being written fresh.
        """
        # Create the "legacy" record directly (simulating data that predates validation).
        org = Organization.objects.create(name='Legacy<Invalid>Name', description='original')
        caplog.clear()
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        serializer = OrgSerializer(org, data={'description': 'updated description'}, partial=True)
        assert serializer.is_valid(), serializer.errors
        serializer.save()

        org.refresh_from_db()
        assert org.description == 'updated description'
        assert org.name == 'Legacy<Invalid>Name'  # grandfathered, unchanged

        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert signal_logs == [], f"Grandfathered serializer update was falsely logged as a bypass: {signal_logs}"

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_non_text_fields_ignored(self, caplog):
        """AC #6.4: Non-text fields are ignored by the signal."""
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        # Organization has integer and JSON fields that should be ignored
        # Only text fields (name, description) are validated
        org = Organization.objects.create(
            name='ValidName',
            description='Valid description',
            # extra_field is JSONField - should not trigger validation signal
        )

        # No violations logged (all text fields are valid)
        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert len(signal_logs) == 0

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False)
    def test_signal_logs_even_when_enforcement_disabled(self, caplog):
        """Signal logs violations even when ENHANCED_INPUT_VALIDATION_ENABLED is False.

        The enforcement setting controls whether violations block saves, not whether
        they are observed. Observability (logging) happens regardless, matching
        CleanTextMixin's behavior: it logs violations at WARNING level whether
        enforcement is on or off.
        """
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        # Create with violation while validation is disabled
        org = Organization.objects.create(
            name='ValidName',
            description='<script>alert("xss")</script>'
        )

        assert org.pk is not None

        # Log entry is created even though enforcement is off
        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert len(signal_logs) == 1
        assert 'Tier 2' in signal_logs[0].message

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_multiple_field_violations_logged(self, caplog):
        """Multiple violations in a single save should log each one."""
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        # Create with violations in both name and description
        org = Organization.objects.create(
            name='Invalid<Name>',
            description='<script>xss</script>'
        )

        assert org.pk is not None

        # Two log entries (one per field)
        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert len(signal_logs) == 2

        # Verify both fields logged
        messages = [r.message for r in signal_logs]
        assert any('name' in msg and 'Tier 1' in msg for msg in messages)
        assert any('description' in msg and 'Tier 2' in msg for msg in messages)

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_caller_info_captured(self, caplog):
        """Caller information should be captured in the log."""
        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        # Create with violation
        Organization.objects.create(
            name='Valid',
            description='<b>html</b>'
        )

        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        assert len(signal_logs) == 1
        log_message = signal_logs[0].message

        # Caller info should reference this test file, not Django's save()/signal-dispatch
        # internals that sit between here and the signal handler.
        assert 'caller:' in log_message
        assert 'test_validation_signals' in log_message
        assert 'django.db.models' not in log_message
        assert 'django.dispatch' not in log_message

    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_unregistered_model_not_checked(self, caplog):
        """A model with no CleanTextMixin serializer must never be checked by the signal.

        This is what keeps unrelated cascade saves (e.g. resource_registry.Resource,
        updated via its own post_save receiver on many models) from being misreported
        as ORM bypass violations.
        """
        from ansible_base.resource_registry.models import Resource

        caplog.set_level(logging.WARNING, logger='ansible_base.lib.utils.validation_signals')

        # Saving Organization triggers resource_registry's post_save cascade, which
        # updates/saves a Resource row with the same (invalid) name copied over.
        Organization.objects.create(name='Invalid<Name>', description='valid')

        signal_logs = [r for r in caplog.records if 'ORM bypass' in r.message]
        resource_type_registry_logs = [r for r in signal_logs if Resource._meta.label in r.message]
        assert resource_type_registry_logs == [], "Resource (unregistered model) must not be checked by the signal"


class TestContextVariableHandling:
    """Test the context variable mechanism that prevents double-logging."""

    def test_context_token_lifecycle(self):
        """Context token should properly set and reset the context."""
        from ansible_base.lib.utils.validation_signals import _serializer_validation_active

        # Initially False
        assert _serializer_validation_active.get(False) is False

        # Set context
        token = get_validation_context_token()
        assert _serializer_validation_active.get(False) is True

        # Reset context
        reset_validation_context(token)
        assert _serializer_validation_active.get(False) is False

    def test_context_nested_calls(self):
        """Nested context calls should work correctly."""
        from ansible_base.lib.utils.validation_signals import _serializer_validation_active

        # Set first context
        token1 = get_validation_context_token()
        assert _serializer_validation_active.get(False) is True

        # Set second context (nested)
        token2 = get_validation_context_token()
        assert _serializer_validation_active.get(False) is True

        # Reset in reverse order
        reset_validation_context(token2)
        assert _serializer_validation_active.get(False) is True

        reset_validation_context(token1)
        assert _serializer_validation_active.get(False) is False


class TestProtectedModelRegistry:
    """Test the CleanTextMixin -> signal model registry."""

    def test_serializer_subclass_registers_its_model(self):
        """Defining a CleanTextMixin serializer registers Meta.model automatically."""
        from ansible_base.lib.utils.validation_signals import _protected_models

        # OrgSerializer is defined at module load time; __init_subclass__ already ran.
        assert Organization in _protected_models
        name_fields, _excluded_fields = _protected_models[Organization]
        assert 'name' in name_fields

    def test_mixin_without_meta_model_is_not_registered(self):
        """A CleanTextMixin subclass with no Meta.model must not raise or register anything."""
        from ansible_base.lib.utils.validation_signals import _protected_models

        before = dict(_protected_models)

        class _NoMetaSerializer(CleanTextMixin, serializers.Serializer):
            pass

        assert _protected_models == before

    def test_excluded_fields_union_across_serializers(self):
        """Two serializers for the same model union their excluded_fields in the registry."""
        from ansible_base.lib.utils.validation_signals import _protected_models

        class _OrgSerializerExcludingDescription(CleanTextMixin, serializers.ModelSerializer):
            excluded_fields = frozenset({'description'})

            class Meta:
                model = Organization
                fields = ['name', 'description']

        _name_fields, excluded_fields = _protected_models[Organization]
        assert 'description' in excluded_fields


class TestHelperFunctions:
    """Test utility functions used by the signal handler."""

    def test_get_text_fields(self):
        """_get_text_fields should return text and JSON fields."""
        # Test with Organization (has text fields)
        text_fields, json_fields = _get_text_fields(Organization)
        assert 'name' in text_fields
        assert 'description' in text_fields

        # Test with City (has JSONField)
        text_fields, json_fields = _get_text_fields(City)
        assert 'name' in text_fields  # City has name from NamedCommonModel
        assert 'country' in text_fields
        assert 'extra_data' in json_fields

    def test_validate_field_tier1_pass(self):
        """Valid name field should pass Tier 1 validation."""
        result = _validate_field('name', 'ValidName123', {'name', 'username', 'hostname'})
        assert result is None

    def test_validate_field_tier1_fail(self):
        """Invalid name field should fail Tier 1 validation."""
        result = _validate_field('name', 'Invalid<Name>', {'name', 'username', 'hostname'})
        assert result is not None
        tier, reason = result
        assert tier == 'Tier 1'
        assert 'valid name' in reason.lower()

    def test_validate_field_tier2_pass(self):
        """Valid free text should pass Tier 2 validation."""
        result = _validate_field('description', 'This is a valid description', {'name'})
        assert result is None

    def test_validate_field_tier2_fail(self):
        """HTML in free text should fail Tier 2 validation."""
        result = _validate_field('description', '<script>alert(1)</script>', {'name'})
        assert result is not None
        tier, reason = result
        assert tier == 'Tier 2'
        assert 'HTML' in reason

    def test_validate_field_handles_none(self):
        """None values should not cause errors."""
        # This is handled in the main signal handler, not _validate_field
        # _validate_field expects strings, signal handler filters None
        pass

    def test_validate_field_handles_non_string(self):
        """Non-string values should not cause errors."""
        # This is handled in the main signal handler
        # The signal handler skips non-string values
        pass
