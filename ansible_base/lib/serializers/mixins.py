import logging

from rest_framework import serializers

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
