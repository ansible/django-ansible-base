from cryptography.hazmat.primitives import serialization
from cryptography.x509 import load_pem_x509_certificate
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.fields import Field as DRField
from rest_framework.fields import SkipField as DRFSkipField
from rest_framework.fields import empty as DRFEmpty

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.validation import validate_url, validate_url_list


class UILabelMixIn:
    def __init__(self, **kwargs):
        self.ui_field_label = kwargs.pop('ui_field_label', 'Undefined')
        super().__init__(**kwargs)


class Field(UILabelMixIn, DRField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class _Forbidden(Field):
    default_error_messages = {'invalid': _('Invalid field.')}

    def run_validation(self, value):
        self.fail('invalid')


class Empty(UILabelMixIn, DRFEmpty):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class SkipField(UILabelMixIn, DRFSkipField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class BooleanField(UILabelMixIn, serializers.BooleanField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class CharField(UILabelMixIn, serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ChoiceField(UILabelMixIn, serializers.ChoiceField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class DictField(UILabelMixIn, serializers.DictField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ListField(UILabelMixIn, serializers.ListField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class JSONField(UILabelMixIn, serializers.JSONField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class URLField(UILabelMixIn, serializers.CharField):
    def __init__(self, **kwargs):
        self.schemes = kwargs.pop('schemes', ['https', 'http'])
        self.allow_plain_hostname = kwargs.pop('allow_plain_hostname', True)
        super().__init__(**kwargs)

        def validator(value):
            return validate_url(value, schemes=self.schemes, allow_plain_hostname=self.allow_plain_hostname)

        self.validators.append(validator)


class URLListField(UILabelMixIn, serializers.ListField):
    def __init__(self, **kwargs):
        self.schemes = kwargs.pop('schemes', ['https', 'http'])
        self.allow_plain_hostname = kwargs.pop('allow_plain_hostname', True)
        super().__init__(**kwargs)

        def validator(value):
            return validate_url_list(value, schemes=self.schemes, allow_plain_hostname=self.allow_plain_hostname)

        self.validators.append(validator)


class UserAttrMap(UILabelMixIn, serializers.DictField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        def validator(value):
            errors = {}

            valid_user_attr_fields = set(["email", "username", "first_name", "last_name"])
            given_fields = set(list(value.keys()))

            missing_required_fields = set(get_user_model().REQUIRED_FIELDS) - given_fields
            for field in missing_required_fields:
                errors[field] = "Must be present"

            invalid_fields = given_fields - valid_user_attr_fields
            for field in invalid_fields:
                errors[field] = "Is not valid"

            valid_fields = given_fields.intersection(valid_user_attr_fields)
            for field in valid_fields:
                if type(value[field]) is not str:
                    errors[field] = "Must be a string"

            if errors:
                raise serializers.ValidationError(errors)

        self.validators.append(validator)


class PublicCert(UILabelMixIn, serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.public_cert = None

        def validator(value):
            if value:
                try:
                    self.public_cert = load_pem_x509_certificate(bytes(value, "UTF-8"))
                except Exception as e:
                    raise serializers.ValidationError(f"Unable to load as PEM data {e}")

        self.validators.append(validator)


class PrivateKey(UILabelMixIn, serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.private_key = None

        def validator(value):
            if value and value != ENCRYPTED_STRING:
                try:
                    self.private_key = serialization.load_pem_private_key(bytes(value, "UTF-8"), password=None)
                except Exception as e:
                    raise serializers.ValidationError(f"Unable to load as PEM data {e}")

        self.validators.append(validator)


###############################################################################
#   SOCIAL
###############################################################################


class GithubPolymorphicField(DRField):
    def to_internal_value(self, data):
        # Validate None
        if data is None:
            return data

        # Validate True/False
        if isinstance(data, bool):
            return data

        # Validate a single string (ensure it's non-empty if you require)
        if isinstance(data, str) and data.strip():
            return data

        # Validate list or tuple of strings
        if isinstance(data, (list, tuple)) and all(isinstance(item, str) and item.strip() for item in data):
            return data

        # If none of the above conditions are met, raise a validation error
        raise ValidationError("Value must be None, a boolean, a non-empty string, or a list/tuple of non-empty strings.")

    def to_representation(self, value):
        # Convert the Python object back into a serializable format
        return value


class GithubOrganizationMapField(DictField):

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise ValidationError("Expected a dictionary of organizations.")

        validated_data = {}
        for org_name, org_data in data.items():
            if not isinstance(org_data, dict) or not set(org_data.keys()).issubset({'users', 'admins'}):
                raise ValidationError(f"{org_name} must contain only 'users' or 'admins' keys.")

            validated_org_data = {}
            # Validate 'users' field using custom UsersField
            if 'users' in org_data:
                users_field = GithubPolymorphicField()
                validated_org_data['users'] = users_field.to_internal_value(org_data['users'])

            # Validate 'admins' field using custom AdminsField
            if 'admins' in org_data:
                admins_field = GithubPolymorphicField()
                validated_org_data['admins'] = admins_field.to_internal_value(org_data['admins'])

            validated_data[org_name] = validated_org_data

        return validated_data


class GithubOrganizationTeamMapField(DictField):

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise ValidationError("Expected a dictionary of organizations.")

        validated_data = {}
        for org_name, org_data in data.items():
            if not isinstance(org_data, dict) or not set(org_data.keys()).issubset({'organization', 'users', 'admins', 'remove'}):
                raise ValidationError(f"{org_name} must contain only 'organization' or 'users' or 'admins' or 'remove' keys.")

            validated_org_data = {}

            if 'organization' in org_data:
                org_field = CharField(required=True)
                validated_org_data['organization'] = org_field.to_internal_value(org_data['organization'])

            # Validate 'users' field using custom UsersField
            if 'users' in org_data:
                users_field = GithubPolymorphicField()
                validated_org_data['users'] = users_field.to_internal_value(org_data['users'])

            # Validate 'admins' field using custom AdminsField
            if 'admins' in org_data:
                admins_field = GithubPolymorphicField()
                validated_org_data['admins'] = admins_field.to_internal_value(org_data['admins'])

            # Validate 'admins' field using custom AdminsField
            if 'remove' in org_data:
                remove_field = BooleanField(default=True)
                validated_org_data['admins'] = remove_field.to_internal_value(org_data['remove'])

            validated_data[org_name] = validated_org_data

        return validated_data
