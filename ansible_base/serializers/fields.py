from django.contrib.auth import get_user_model
from rest_framework import serializers

from ansible_base.utils.validation import validate_url, validate_url_list

User = get_user_model()


class URLField(serializers.CharField):
    def __init__(self, **kwargs):
        self.schemes = kwargs.pop('schemes', ['https', 'http'])
        self.allow_plain_hostname = kwargs.pop('allow_plain_hostname', True)
        super().__init__(**kwargs)

        def validator(value):
            return validate_url(value, schemes=self.schemes, allow_plain_hostname=self.allow_plain_hostname)

        self.validators.append(validator)


class URLListField(serializers.ListField):
    def __init__(self, **kwargs):
        self.schemes = kwargs.pop('schemes', ['https', 'http'])
        self.allow_plain_hostname = kwargs.pop('allow_plain_hostname', True)
        super().__init__(**kwargs)

        def validator(value):
            return validate_url_list(value, schemes=self.schemes, allow_plain_hostname=self.allow_plain_hostname)

        self.validators.append(validator)


class UserAttrMap(serializers.DictField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        def validator(value):
            errors = {}

            valid_user_attr_fields = set(["email", "username", "first_name", "last_name"])
            given_fields = set(list(value.keys()))

            missing_required_fields = set(User.REQUIRED_FIELDS) - given_fields
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
