import logging
import unicodedata

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.utils.validation import DEFAULT_NAME_FIELDS, validate_free_text, validate_resource_name

logger = logging.getLogger('ansible_base.lib.serializers.mixins')


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

    See docs/lib/validation.md for the full contract.
    """

    name_fields = DEFAULT_NAME_FIELDS
    excluded_fields = frozenset()

    def validate(self, attrs):
        model = self.Meta.model
        # We use get_internal_type() rather than isinstance() here deliberately.
        # isinstance(f, (CharField, TextField)) would also catch SlugField and
        # URLField — format-constrained subclasses that have their own validators
        # and are not free-text fields per ANSTRAT-1756. Those subclasses override
        # get_internal_type() to return their own name (e.g. "SlugField"), so they
        # are naturally excluded by this check. Custom free-text subclasses (e.g.
        # EncryptedTextField) typically do NOT override get_internal_type(), so they
        # inherit "CharField"/"TextField" and are caught here automatically.
        text_fields = [f.name for f in model._meta.get_fields() if hasattr(f, 'get_internal_type') and f.get_internal_type() in ('CharField', 'TextField')]

        errors = {}
        for field_name in text_fields:
            if field_name in self.excluded_fields:
                continue
            if field_name not in attrs:
                continue
            value = attrs[field_name]
            if not isinstance(value, str):
                continue

            # On update, skip if value hasn't changed (grandfather)
            if self.instance and getattr(self.instance, field_name, None) == value:
                continue

            # Apply appropriate validator based on field type
            if field_name in self.name_fields:
                try:
                    validate_resource_name(unicodedata.normalize('NFC', value))
                except serializers.ValidationError as exc:
                    errors[field_name] = exc.detail
            else:
                try:
                    validate_free_text(value)
                except serializers.ValidationError as exc:
                    errors[field_name] = exc.detail

        if errors:
            raise serializers.ValidationError(errors)

        return super().validate(attrs)


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
