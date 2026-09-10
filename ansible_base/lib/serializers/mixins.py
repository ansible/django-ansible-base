import logging
import re
from types import MappingProxyType

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.validation import DEFAULT_NAME_FIELDS, validate_free_text, validate_resource_name

logger = logging.getLogger('ansible_base.lib.serializers.mixins')

_INCOMPLETE_VALIDATION_MSG = _("Validation could not be completed for this field.")
_LOG_CONTROL_RE = re.compile(r'[\x00-\x1f\x7f-\x9f]')


class CleanTextMixin:
    """
    Drop-in mixin for DRF ModelSerializer that rejects unsafe text input.
    Must appear before ModelSerializer in MRO.

    Usage::

        from ansible_base.lib.serializers.mixins import CleanTextMixin

        class MySerializer(CleanTextMixin, serializers.ModelSerializer):
            class Meta:
                model = MyModel
                fields = '__all__'

    Tier 1 (name fields): strict character allowlist via validate_resource_name.
    Tier 2 (all other CharField/TextField): dangerous-pattern blocklist via validate_free_text.
    On update, unchanged fields are grandfathered (skipped).

    Configurable attributes:
        name_fields: field names routed to Tier 1 (default: name, username, hostname).
        excluded_fields: field names skipped entirely — use for fields that legitimately
            contain HTML or template syntax (e.g. Jinja2 templates, custom login HTML).
            Also skips entire JSONFields when listed here.
        excluded_json_keys: mapping of JSONField name to a frozenset of sub-keys
            that should be skipped during validation (e.g. PEM keys, template content).
            Example: {'inputs': frozenset({'ssh_key_data'})}

    See docs/lib/validation.md for the full contract.
    """

    name_fields = DEFAULT_NAME_FIELDS
    excluded_fields = frozenset()
    excluded_json_keys = MappingProxyType({})

    def _log_validation_failure(self, field_name, detail):
        """Emit a WARNING-level audit log for a rejected field value.

        Only the validator's own error message is recorded — never the raw input.
        """
        resource_type = f"{self.Meta.model._meta.app_label}.{self.Meta.model._meta.object_name}"
        if isinstance(detail, list):
            reason = '; '.join(str(d) for d in detail)
        else:
            reason = str(detail)

        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if user and getattr(user, 'is_authenticated', False):
            user_fragment = f" for user {user.username}"
        else:
            user_fragment = ""

        client_ip = ''
        if request:
            xff = request.META.get('HTTP_X_FORWARDED_FOR')
            raw_ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')
            client_ip = _LOG_CONTROL_RE.sub(lambda m: repr(m.group())[1:-1], raw_ip)

        ip_fragment = f" (ip {client_ip})" if client_ip else ""

        logger.warning("Validation rejected '%s' on %s%s%s: %s", field_name, resource_type, user_fragment, ip_fragment, reason)

    def validate(self, attrs):
        enforce = get_setting('ENHANCED_INPUT_VALIDATION_ENABLED', False)
        model = self.Meta.model

        text_fields, json_fields = self._classify_fields(model)

        errors = {}
        self._validate_text_fields(text_fields, attrs, errors)
        self._validate_json_fields(json_fields, attrs, errors)

        if errors and enforce:
            raise serializers.ValidationError(errors)

        return super().validate(attrs)

    def _classify_fields(self, model):
        """Partition model fields into (text_fields, json_fields) in a single traversal."""
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

    def _is_unchanged(self, field_name, value):
        """True when the instance already stores an identical value (grandfather rule)."""
        return self.instance and getattr(self.instance, field_name, None) == value

    def _validate_text_fields(self, field_names, attrs, errors):
        """Validate CharField / TextField values (Tier 1 name fields + Tier 2 free-text).

        We use get_internal_type() rather than isinstance() here deliberately.
        isinstance(f, (CharField, TextField)) would also catch SlugField and
        URLField — format-constrained subclasses that have their own validators
        and are not free-text fields per ANSTRAT-1756. Those subclasses override
        get_internal_type() to return their own name (e.g. "SlugField"), so they
        are naturally excluded by this check. Custom free-text subclasses (e.g.
        EncryptedTextField) typically do NOT override get_internal_type(), so they
        inherit "CharField"/"TextField" and are caught here automatically.
        """
        for field_name in field_names:
            if field_name in self.excluded_fields or field_name not in attrs:
                continue
            value = attrs[field_name]
            if not isinstance(value, str) or self._is_unchanged(field_name, value):
                continue
            self._run_text_validator(field_name, value, errors)

    def _run_text_validator(self, field_name, value, errors):
        """Apply the appropriate validator (name vs free-text) and collect errors."""
        try:
            if field_name in self.name_fields:
                validate_resource_name(value)
            else:
                validate_free_text(value)
        except serializers.ValidationError as exc:
            errors[field_name] = exc.detail
            self._log_validation_failure(field_name, exc.detail)
        except Exception:
            logger.exception("Unexpected error validating field '%s'", field_name)
            if get_setting('ENHANCED_INPUT_VALIDATION_ENABLED', False):
                errors[field_name] = [_INCOMPLETE_VALIDATION_MSG]

    _MAX_JSON_DEPTH = 10

    def _validate_json_fields(self, field_names, attrs, errors):
        """Validate string values inside JSONFields (recursive traversal)."""
        for field_name in field_names:
            if field_name in self.excluded_fields or field_name not in attrs:
                continue
            json_errors = self._validate_json_field(field_name, attrs[field_name])
            if json_errors:
                errors[field_name] = json_errors

    def _validate_json_field(self, field_name, value):
        """Validate a single JSONField value and return any nested errors.

        For bare strings, returns errors as a flat list (not wrapped in a sub-key
        dict) so the caller can assign them directly to errors[field_name].
        """
        excluded_keys = self.excluded_json_keys.get(field_name, frozenset())
        stored_value = getattr(self.instance, field_name, None) if self.instance else None

        if isinstance(value, str):
            if self._is_unchanged(field_name, value):
                return None
            try:
                validate_free_text(value)
            except serializers.ValidationError as exc:
                self._log_validation_failure(field_name, exc.detail)
                return exc.detail
            except Exception:
                logger.exception("Unexpected error validating field '%s'", field_name)
                if get_setting('ENHANCED_INPUT_VALIDATION_ENABLED', False):
                    return [_INCOMPLETE_VALIDATION_MSG]
            return None

        json_errors = {}
        if isinstance(value, dict):
            self._validate_json_dict(value, excluded_keys, json_errors, field_name=field_name, stored_data=stored_value)
        elif isinstance(value, list):
            self._validate_json_list(value, excluded_keys, json_errors, field_name=field_name, stored_data=stored_value)

        return json_errors or None

    def _validate_json_string(self, val, qualified_key, errors, field_name):
        """Validate a single JSON string value and collect errors."""
        try:
            validate_free_text(val)
        except serializers.ValidationError as exc:
            errors[qualified_key] = exc.detail
            log_field = f"{field_name}.{qualified_key}" if field_name else qualified_key
            self._log_validation_failure(log_field, exc.detail)
        except Exception:
            logger.exception("Unexpected error validating JSON key '%s'", qualified_key)
            if get_setting('ENHANCED_INPUT_VALIDATION_ENABLED', False):
                errors[qualified_key] = [_INCOMPLETE_VALIDATION_MSG]

    def _check_json_depth_limit(self, depth, errors, key_prefix, field_name):
        """Return True and record an error if the JSON depth limit is exceeded."""
        if depth < self._MAX_JSON_DEPTH:
            return False
        logger.warning("JSON validation depth limit (%d) reached for field '%s' — deeper values were not validated", self._MAX_JSON_DEPTH, field_name)
        error_key = key_prefix.rstrip('.') or field_name
        errors[error_key] = [_INCOMPLETE_VALIDATION_MSG]
        return True

    def _validate_json_dict(self, data, skip_keys, errors, key_prefix="", field_name="", stored_data=None, depth=0):
        """Validate values in a JSON dict, recursing into nested structures."""
        if self._check_json_depth_limit(depth, errors, key_prefix, field_name):
            return
        for key, val in data.items():
            if key in skip_keys:
                continue
            safe_key = _LOG_CONTROL_RE.sub(lambda m: repr(m.group())[1:-1], key) if isinstance(key, str) else key
            qualified_key = f"{key_prefix}{safe_key}"
            stored_val = stored_data.get(key) if isinstance(stored_data, dict) else None

            if isinstance(val, str):
                if val == stored_val:
                    continue
                self._validate_json_string(val, qualified_key, errors, field_name)
            elif isinstance(val, dict):
                self._validate_json_dict(val, skip_keys, errors, key_prefix=f"{qualified_key}.", field_name=field_name, stored_data=stored_val, depth=depth + 1)
            elif isinstance(val, list):
                self._validate_json_list(val, skip_keys, errors, key_prefix=qualified_key, field_name=field_name, stored_data=stored_val, depth=depth + 1)

    def _validate_json_list(self, data, skip_keys, errors, key_prefix="", field_name="", stored_data=None, depth=0):
        """Validate values in a JSON list, recursing into nested structures."""
        if self._check_json_depth_limit(depth, errors, key_prefix, field_name):
            return
        for idx, item in enumerate(data):
            stored_item = stored_data[idx] if isinstance(stored_data, list) and idx < len(stored_data) else None
            item_key = f"{key_prefix}[{idx}]"

            if isinstance(item, str):
                if item == stored_item:
                    continue
                self._validate_json_string(item, item_key, errors, field_name)
            elif isinstance(item, dict):
                self._validate_json_dict(item, skip_keys, errors, key_prefix=f"{item_key}.", field_name=field_name, stored_data=stored_item, depth=depth + 1)
            elif isinstance(item, list):
                self._validate_json_list(item, skip_keys, errors, key_prefix=item_key, field_name=field_name, stored_data=stored_item, depth=depth + 1)


# Derived from: https://github.com/encode/django-rest-framework/discussions/8606
class ImmutableFieldsMixin(serializers.ModelSerializer):
    # Mixin enabling the usage of Meta.immutable_fields for setting fields read_only after object creation.

    # Currently, using this without issues requires outside considerations:
    #     1. overrides to get_serializer for the related viewsets,
    #        since by default, rest_framework's SimpleMetadata class does not try to provide initialize a serializer
    #        with an instance value on elements with a primary key field.

    #        See ansible_base.authentication.views.AuthenticatorViewSet for an example.
    #    2. The generated OpenAPI spec will treat immutable fields as valid parameters on PUT and PATCH endpoints

    def get_extra_kwargs(self):
        kwargs = super().get_extra_kwargs()
        immutable_fields = getattr(self.Meta, "immutable_fields", [])

        # Make field read_only if instance already exists
        for field in immutable_fields:
            kwargs.setdefault(field, {})
            kwargs[field]["read_only"] = bool(self.instance)

        return kwargs


class EmailAdminOnlyMixin:
    """Mixin for User serializers that restricts email changes to admins.

    Uses can_change_user with can_self_edit=False so that only superusers
    and org admins can update the email field. Services that set
    ALLOW_USER_EMAIL_SELF_EDIT=True override this and allow regular users to
    change their own email.
    """

    def validate_email(self, value):
        if self.instance is None or value == self.instance.email:
            return value

        request = self.context.get('request')
        if request is None:
            return value

        from ansible_base.rbac.policies import can_change_user

        if not can_change_user(request.user, self.instance, can_self_edit=False):
            raise PermissionDenied("Email updates are restricted to administrators.")

        return value
