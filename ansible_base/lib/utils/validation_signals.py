"""Django signal handler to detect ORM-direct writes that bypass CleanTextMixin validation.

When models are saved directly via ORM methods (Model.objects.create(), instance.save(),
queryset.update(), etc.) rather than through DRF serializers, they bypass the CleanTextMixin
validation layer. This signal handler provides observability by logging validation
violations that occur through these bypass paths.

This is defense-in-depth observability — it does NOT block saves, only logs them.

Known limitation: Django does not send post_save (or any) signals for bulk_create(),
bulk_update(), or QuerySet.update() -- see docs/lib/validation_bypass_paths.md. Those
paths are NOT observable via this signal; model-level validators are the only way to
cover them (see docs/lib/validation.md).
"""
import inspect
import logging
from contextvars import ContextVar
from typing import Optional

from django.db.models import Model
from django.db.models.signals import post_save
from rest_framework.serializers import ValidationError

from ansible_base.lib.utils.validation import validate_free_text, validate_resource_name

logger = logging.getLogger('ansible_base.lib.utils.validation_signals')

# Context variable to track when a save originates from CleanTextMixin-mediated
# serializer.save() so the signal handler can skip it (avoids double-logging).
_serializer_validation_active: ContextVar[bool] = ContextVar('serializer_validation_active', default=False)

# Registry of models that have at least one serializer using CleanTextMixin, populated by
# CleanTextMixin.__init_subclass__. The signal only inspects models in this registry --
# this scopes checks to AC #1 ("models that are covered by CleanTextMixin in their
# serializers") and keeps unrelated models (e.g. resource_registry.Resource, which is
# saved as a side effect of post_save cascades) from generating false-positive log entries.
# Maps model -> (name_fields: frozenset[str], excluded_fields: frozenset[str])
_protected_models: dict[type, tuple[frozenset, frozenset]] = {}

# Frame modules to skip when walking the stack for caller info -- these are the
# save()/signal-dispatch internals between the real caller and this signal handler,
# not useful information for an auditor tracing the bypass back to its source.
_INTERNAL_CALLER_PREFIXES = (
    'django.db.models',
    'django.dispatch',
    'ansible_base.lib.utils.validation_signals',
)


def get_validation_context_token():
    """Get a context token for CleanTextMixin.save() to set while persisting a validated instance.

    Returns a token that should be passed to reset_validation_context() in a finally block.
    """
    return _serializer_validation_active.set(True)


def reset_validation_context(token):
    """Reset the validation context using the token from get_validation_context_token()."""
    _serializer_validation_active.reset(token)


def register_protected_model(model: type, name_fields: frozenset, excluded_fields: frozenset) -> None:
    """Register a model as covered by a CleanTextMixin serializer.

    Called by CleanTextMixin.__init_subclass__ for every serializer subclass. If the same
    model is registered by multiple serializers (e.g. different services with different
    name_fields/excluded_fields configurations), the sets are unioned so the signal checks
    the broadest configuration seen across all registered serializers for that model.
    """
    existing_name_fields, existing_excluded_fields = _protected_models.get(model, (frozenset(), frozenset()))
    _protected_models[model] = (
        existing_name_fields | name_fields,
        existing_excluded_fields | excluded_fields,
    )


def _get_text_fields(model: type[Model]) -> tuple[list[str], list[str]]:
    """Get (text_fields, json_fields) for a model using same logic as CleanTextMixin._classify_fields().

    Returns:
        Tuple of (text_field_names, json_field_names)
    """
    text_fields = []
    json_fields = []
    for f in model._meta.get_fields():
        if not hasattr(f, 'get_internal_type'):
            continue
        itype = f.get_internal_type()
        if itype in ('CharField', 'TextField'):
            text_fields.append(f.name)
        elif itype == 'JSONField':
            json_fields.append(f.name)
    return text_fields, json_fields


def _get_caller_info() -> str:
    """Walk the call stack to find the real caller that triggered this save.

    Skips frames belonging to Django's save()/signal-dispatch machinery and this module's
    own functions, returning the first frame outside of those -- i.e. the actual
    application code that invoked .save() / .create() / etc.

    Returns:
        String like "module.function:line" or "unknown" if no such frame is found.
    """
    try:
        for frame_info in inspect.stack()[1:]:
            module = inspect.getmodule(frame_info.frame)
            module_name = module.__name__ if module else ''
            if module_name.startswith(_INTERNAL_CALLER_PREFIXES):
                continue
            return f"{module_name or 'unknown'}.{frame_info.function}:{frame_info.lineno}"
        return "unknown"
    except Exception:
        # Stack introspection can fail in some environments (e.g., certain test runners)
        return "unknown"


def _validate_field(field_name: str, value: str, name_fields: frozenset) -> Optional[tuple[str, str]]:
    """Validate a single text field and return violation info if it fails.

    Args:
        field_name: Name of the field being validated
        value: Value to validate
        name_fields: Set of field names that should use Tier 1 (name) validation

    Returns:
        Tuple of (tier, reason) if validation fails, None if passes
        - tier: "Tier 1" or "Tier 2"
        - reason: The validation error message
    """
    try:
        if field_name in name_fields:
            validate_resource_name(value)
        else:
            validate_free_text(value)
        return None
    except ValidationError as exc:
        tier = "Tier 1" if field_name in name_fields else "Tier 2"
        if isinstance(exc.detail, list):
            reason = '; '.join(str(d) for d in exc.detail)
        else:
            reason = str(exc.detail)
        return (tier, reason)
    except Exception:
        # Unexpected validation errors should not break the save
        logger.exception("Unexpected error during ORM bypass validation check for field '%s'", field_name)
        return None


def validation_bypass_logger(sender, instance: Model, created: bool, **kwargs):
    """Signal handler for post_save that logs ORM-direct writes bypassing CleanTextMixin.

    This handler:
    1. Skips models with no registered CleanTextMixin serializer (fast short-circuit)
    2. Checks if the save originated from a serializer's save() (via context var)
    3. Identifies text fields on the model
    4. Validates field values against Tier 1/Tier 2 rules
    5. Logs violations with structured audit information
    6. Never blocks the save (observability-only)

    Args:
        sender: The model class
        instance: The model instance being saved
        created: True if this was an INSERT, False if UPDATE
        **kwargs: Additional signal kwargs
    """
    # Skip models that have no serializer using CleanTextMixin -- out of scope per AC #1,
    # and prevents false positives from unrelated models saved as a side effect of this
    # save (e.g. resource_registry.Resource, synced via its own post_save handler).
    protected = _protected_models.get(sender)
    if protected is None:
        return
    name_fields, excluded_fields = protected

    # Skip if this save originated from a DRF serializer with CleanTextMixin
    if _serializer_validation_active.get(False):
        return

    # Skip if enhanced validation is not configured (no validators to check against)
    from ansible_base.lib.utils.settings import get_setting
    if not get_setting('ENHANCED_INPUT_VALIDATION_ENABLED', False):
        # Validation is not enabled, so we shouldn't log bypass attempts
        # (logging would be noise since the validators aren't enforced anyway)
        return

    # Get text fields for this model
    text_fields, _json_fields = _get_text_fields(sender)
    if not text_fields:
        # No text fields to validate
        return

    # Get caller information for the audit log
    caller_info = _get_caller_info()

    # Validate each text field and log violations
    resource_type = f"{instance._meta.app_label}.{instance._meta.object_name}"

    for field_name in text_fields:
        if field_name in excluded_fields:
            continue

        value = getattr(instance, field_name, None)

        # Skip None and non-string values
        if value is None or not isinstance(value, str):
            continue

        # Validate the field
        violation = _validate_field(field_name, value, name_fields)

        if violation:
            tier, reason = violation
            # Log in the same format as CleanTextMixin._log_validation_failure()
            # but with "ORM bypass" prefix and caller info
            logger.warning(
                "ORM bypass: validation rejected '%s' on %s (violates %s) [caller: %s]: %s",
                field_name,
                resource_type,
                tier,
                caller_info,
                reason,
            )


def register_validation_signals():
    """Register the validation bypass logging signal.

    This should be called from an AppConfig.ready() method to enable ORM bypass detection.
    """
    post_save.connect(validation_bypass_logger, dispatch_uid='validation-bypass-logger', weak=False)
    logger.debug("Registered validation bypass logging signal")
