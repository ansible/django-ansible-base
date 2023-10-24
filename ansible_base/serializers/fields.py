from rest_framework import serializers

from ansible_base.utils.validation import validate_url


class URLField(serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        def validator(value):
            return validate_url(value, schemes=["https", "http"], allow_plain_hostname=True)

        self.validators.append(validator)
