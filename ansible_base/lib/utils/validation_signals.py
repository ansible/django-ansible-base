"""Django signal handler to detect ORM-direct writes that bypass CleanTextMixin validation.

When models are saved directly via ORM methods (Model.objects.create(), instance.save(),
queryset.update(), etc.) rather than through DRF serializers, they bypass the CleanTextMixin
validation layer. This signal handler provides observability by logging validation
violations that occur through these bypass paths.

This is defense-in-depth observability — it does NOT block saves, only logs them.

Known limitation: Django does not send post_save (or any) signals for bulk_create(),
bulk_update(), or QuerySet.update() -- see docs/lib/validation_bypass_observability.md. Use
ansible_base.lib.utils.bulk_validation_audit for optional audit hooks at bulk write sites.
"""

import inspect
import logging
from contextvars import ContextVar
from typing import Optional

from django.db.models import Model
from django.db.models.signals import post_save
from rest_framework.serializers import ValidationError

from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.validation import validate_free_text, validate_resource_name

LOGGER_NAME = __name__
logger = logging.getLogger(LOGGER_NAME)

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

# Denylist: framework plumbing frames to skip during caller resolution (phase 2).
_INTERNAL_CALLER_PREFIXES: list[str] = [
    'django.db.models',
    'django.dispatch',
    LOGGER_NAME,
    'ansible_base.lib.abstract_models',
]

# Allowlist: product-code entry points (phase 1). Also populated from
# CALLER_INFO_APP_MODULES and extend_caller_allowlist_prefixes().
_RUNTIME_ALLOWLIST_PREFIXES: list[str] = []

# Modules skipped during fallback (phase 3) after allowlist and denylist miss.
_FALLBACK_SKIP_PREFIXES = (
    'django.',
    LOGGER_NAME,
    'ansible_base.lib.utils.bulk_validation_audit',
)


def get_validation_context_token():
    """Get a context token for CleanTextMixin.save() to set while persisting a validated instance.

    Returns a token that should be passed to reset_validation_context() in a finally block.
    """
    return _serializer_validation_active.set(True)


def reset_validation_context(token):
    """Reset the validation context using the token from get_validation_context_token()."""
    _serializer_validation_active.reset(token)


def extend_internal_caller_prefixes(prefixes: list[str]) -> None:
    """Register service-internal module prefixes to skip during caller denylist walk (phase 2).

    Downstream services override model ``save()`` in base model modules; register those
    prefixes from ``AppConfig.ready()`` so denylist resolution does not stop on wrappers.
    """
    for prefix in prefixes:
        if prefix and prefix not in _INTERNAL_CALLER_PREFIXES:
            _INTERNAL_CALLER_PREFIXES.append(prefix)


def extend_caller_allowlist_prefixes(prefixes: list[str]) -> None:
    """Register module prefixes treated as real application call sites (phase 1).

    Prefer narrow prefixes (tasks, API views, management commands), not entire app trees.
    """
    for prefix in prefixes:
        if prefix and prefix not in _RUNTIME_ALLOWLIST_PREFIXES:
            _RUNTIME_ALLOWLIST_PREFIXES.append(prefix)


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


def _caller_allowlist_prefixes() -> tuple[str, ...]:
    configured = get_setting('CALLER_INFO_APP_MODULES', []) or []
    merged: list[str] = []
    for prefix in list(configured) + _RUNTIME_ALLOWLIST_PREFIXES:
        if prefix and prefix not in merged:
            merged.append(prefix)
    return tuple(merged)


def _frame_module_and_label(frame) -> tuple[str, str]:
    module_name = frame.f_globals.get('__name__', '') or ''
    label = f"{module_name or 'unknown'}.{frame.f_code.co_name}:{frame.f_lineno}"
    return module_name, label


def _iter_caller_frames():
    """Yield stack frames outward from the caller of ``_get_caller_info`` (cheap walk)."""
    frame = inspect.currentframe()
    if frame is not None:
        frame = frame.f_back
    while frame is not None:
        yield frame
        frame = frame.f_back


def _get_caller_info() -> str:
    """Resolve audit caller using allowlist, then denylist, then fallback.

    Walks frames outward from the caller (phase 1 → 2 → 3).
    """
    try:
        frames = list(_iter_caller_frames())
        allowlist = _caller_allowlist_prefixes()
        denylist = tuple(_INTERNAL_CALLER_PREFIXES)

        if allowlist:
            for frame in frames:
                module_name, label = _frame_module_and_label(frame)
                if module_name.startswith(allowlist):
                    return label

        for frame in frames:
            module_name, label = _frame_module_and_label(frame)
            if module_name.startswith(denylist):
                continue
            return label

        for frame in frames:
            module_name, label = _frame_module_and_label(frame)
            if module_name.startswith(_FALLBACK_SKIP_PREFIXES):
                continue
            return label

        return "unknown"
    except Exception:
        return "unknown"


def log_orm_bypass_violation(
    operation: str,
    field_name: str,
    resource_type: str,
    tier: str,
    caller_info: str,
    reason: str,
) -> None:
    """Emit a structured ORM bypass WARNING (observability only; does not block writes)."""
    logger.warning(
        "ORM bypass (%s): validation rejected '%s' on %s (violates %s) [caller: %s]: %s",
        operation,
        field_name,
        resource_type,
        tier,
        caller_info,
        reason,
    )


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
    protected = _protected_models.get(sender)
    if protected is None:
        return
    name_fields, excluded_fields = protected

    if _serializer_validation_active.get(False):
        return

    text_fields, _json_fields = _get_text_fields(sender)
    if not text_fields:
        return

    caller_info = None
    resource_type = f"{instance._meta.app_label}.{instance._meta.object_name}"

    for field_name in text_fields:
        if field_name in excluded_fields:
            continue

        value = getattr(instance, field_name, None)

        if value is None or not isinstance(value, str):
            continue

        violation = _validate_field(field_name, value, name_fields)

        if violation:
            tier, reason = violation
            if caller_info is None:
                caller_info = _get_caller_info()
            log_orm_bypass_violation(
                "post_save",
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
