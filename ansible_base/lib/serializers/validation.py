#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

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
