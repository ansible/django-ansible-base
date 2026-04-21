import logging

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger('ansible_base.lib.serializers.mixins')


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
    ALLOW_USER_SELF_EDIT=True override this and allow regular users to
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
