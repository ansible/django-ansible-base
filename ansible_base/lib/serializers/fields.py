import collections
import copy
import re

import six
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


class HybridDictField(DictField):
    """A DictField, but with defined fixed Fields for certain keys."""

    def __init__(self, *args, **kwargs):
        self.allow_blank = kwargs.pop('allow_blank', False)

        fields = [
            sorted(
                ((field_name, obj) for field_name, obj in cls.__dict__.items() if isinstance(obj, Field) and field_name != 'child'),
                key=lambda x: x[1]._creation_counter,
            )
            for cls in reversed(self.__class__.__mro__)
        ]
        self._declared_fields = collections.OrderedDict(f for group in fields for f in group)

        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        fields = copy.deepcopy(self._declared_fields)
        return {
            key: field.to_representation(val) if val is not None else None
            for key, val, field in ((six.text_type(key), val, fields.get(key, self.child)) for key, val in value.items())
            if not field.write_only
        }

    def run_child_validation(self, data):
        result = {}

        if not data and self.allow_blank:
            return result

        errors = collections.OrderedDict()
        fields = copy.deepcopy(self._declared_fields)
        keys = set(fields.keys()) | set(data.keys())

        for key in keys:
            value = data.get(key, Empty)
            key = six.text_type(key)
            field = fields.get(key, self.child)
            try:
                if field.read_only:
                    continue  # Ignore read_only fields, as Serializer seems to do.
                result[key] = field.run_validation(value)
            except ValidationError as e:
                errors[key] = e.detail
            except SkipField:
                pass

        if not errors:
            return result
        raise ValidationError(errors)


class SocialMapStringRegexField(CharField):
    def to_representation(self, value):
        if isinstance(value, type(re.compile(''))):
            flags = []
            if value.flags & re.I:
                flags.append('i')
            if value.flags & re.M:
                flags.append('m')
            return '/{}/{}'.format(value.pattern, ''.join(flags))
        else:
            return super(SocialMapStringRegexField, self).to_representation(value)

    def to_internal_value(self, data):
        data = super(SocialMapStringRegexField, self).to_internal_value(data)
        match = re.match(r'^/(?P<pattern>.*)/(?P<flags>[im]+)?$', data)
        if match:
            flags = 0
            if match.group('flags'):
                if 'i' in match.group('flags'):
                    flags |= re.I
                if 'm' in match.group('flags'):
                    flags |= re.M
            try:
                return re.compile(match.group('pattern'), flags)
            except re.error as e:
                raise ValidationError('{}: {}'.format(e, data))
        return data


class SocialMapField(ListField):
    default_error_messages = {'type_error': _('Expected None, True, False, a string or list of strings but got {input_type} instead.')}
    child = SocialMapStringRegexField()

    def to_representation(self, value):
        if isinstance(value, (list, tuple)):
            return super(SocialMapField, self).to_representation(value)
        elif value in BooleanField.TRUE_VALUES:
            return True
        elif value in BooleanField.FALSE_VALUES:
            return False
        elif value in BooleanField.NULL_VALUES:
            return None
        elif isinstance(value, (str, type(re.compile('')))):
            return self.child.to_representation(value)
        else:
            self.fail('type_error', input_type=type(value))

    def to_internal_value(self, data):
        if isinstance(data, (list, tuple)):
            return super(SocialMapField, self).to_internal_value(data)
        elif data in BooleanField.TRUE_VALUES:
            return True
        elif data in BooleanField.FALSE_VALUES:
            return False
        elif data in BooleanField.NULL_VALUES:
            return None
        elif isinstance(data, str):
            return self.child.run_validation(data)
        else:
            self.fail('type_error', input_type=type(data))


class SocialSingleOrganizationMapField(HybridDictField):
    admins = SocialMapField(allow_null=True, required=False)
    users = SocialMapField(allow_null=True, required=False)
    remove_admins = BooleanField(required=False)
    remove_users = BooleanField(required=False)
    organization_alias = SocialMapField(allow_null=True, required=False)

    child = _Forbidden()


class SocialOrganizationMapField(DictField):
    child = SocialSingleOrganizationMapField()


class SocialSingleTeamMapField(HybridDictField):
    organization = CharField()
    users = SocialMapField(allow_null=True, required=False)
    remove = BooleanField(required=False)

    child = _Forbidden()


class SocialTeamMapField(DictField):
    child = SocialSingleTeamMapField()
