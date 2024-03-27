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
import time

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework.views import APIView

from ansible_base.lib.utils.settings import get_function_from_setting, get_setting

logger = logging.getLogger('ansible_base.lib.utils.views.ansible_base')


def convert_to_create_serializer(cls):
    """Given a DRF serializer class, return a modified version that only lists read-only fields

    This is done for eda-server which auto-generates a client library from
    https://github.com/OpenAPITools/openapi-generator
    For fields required in responses, but not used in requests, OpenAPI readOnly is insufficient,
    this recommends two different schemas when _really_ needed for _generated_ code
    https://github.com/OpenAPITools/openapi-generator/issues/14280#issuecomment-1435960939
    """
    create_field_list = []
    for field_name, field in cls().fields.items():
        if not field.read_only:
            create_field_list.append(field_name)

    class Meta(cls.Meta):
        fields = create_field_list

    create_serializer_name = cls.__name__.replace("Serializer", "") + "CreateSerializer"
    return type(create_serializer_name, (cls,), {"Meta": Meta})


class AnsibleBaseView(APIView):
    def get_serializer_class(self):
        serializer_cls = super().get_serializer_class()
        if settings.ANSIBLE_BASE_AUTO_CREATE_SERIALIZER and self.action == "create":
            return convert_to_create_serializer(serializer_cls)
        return serializer_cls

    def initialize_request(self, request, *args, **kwargs):
        """
        Store the Django REST Framework Request object as an attribute on the
        normal Django request, store time the request started.
        """
        self.time_started = time.time()

        return super().initialize_request(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        if request.user and request.user.is_authenticated:
            version = _('Unknown')
            setting = 'ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION'
            the_function = None
            try:
                the_function = get_function_from_setting(setting)
            except Exception:
                logger.exception(_('Failed to load function from {setting} (see exception)'.format(setting=setting)))

            if the_function:
                try:
                    version = the_function()
                except Exception:
                    logger.exception(_('{setting} was set but calling it as a function failed (see exception).'.format(setting=setting)))

            response['X-API-Product-Version'] = version

        response['X-API-Product-Name'] = get_setting('ANSIBLE_BASE_PRODUCT_NAME', _('Unnamed'))
        response['X-API-Node'] = get_setting('CLUSTER_HOST_ID', _('Unknown'))

        time_started = getattr(self, 'time_started', None)
        if time_started:
            time_elapsed = time.time() - self.time_started
            response['X-API-Time'] = '%0.3fs' % time_elapsed

        if getattr(self, 'deprecated', False):
            response['Warning'] = _('This resource has been deprecated and will be removed in a future release.')

        return response
