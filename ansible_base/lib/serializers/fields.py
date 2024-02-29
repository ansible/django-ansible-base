from cryptography.hazmat.primitives import serialization
from cryptography.x509 import load_pem_x509_certificate
from django.contrib.auth import get_user_model
from rest_framework import serializers

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.validation import validate_url, validate_url_list


class UILabelMixIn:
    def __init__(self, **kwargs):
        self.ui_field_label = kwargs.pop('ui_field_label', 'Undefined')
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


class IntegerField(UILabelMixIn, serializers.IntegerField):
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
