import logging

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import APIException
from rest_framework.fields import BooleanField

from ansible_base.lib.utils.validation import to_python_boolean

logger = logging.getLogger('ansible_base.lib.serializers.validation')

validate_field = 'validate'


class APIException202(APIException):
    status_code = 202


class ValidationSerializerMixin:
    model_validate = BooleanField(default=False, write_only=True)

    def save(self, **kwargs):
        want_validate = to_python_boolean(self.context['request'].query_params.get(validate_field, False))

        if not want_validate:
            return super().save(**kwargs)

        with transaction.atomic():
            # If the save fails it will raise an exception and the transaction will be aborted
            super().save(**kwargs)
            # Otherwise we need to raise our own exception to roll back the transaction
            raise APIException202(_("Request would have been accepted"))
