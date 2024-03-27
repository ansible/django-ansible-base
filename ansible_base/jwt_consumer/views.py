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

import inspect
import logging
from os.path import dirname, join
from urllib.parse import urlparse, urlunsplit

from django.http import HttpResponse, HttpResponseNotFound
from django.template import Context, Template
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions, permissions

from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView

logger = logging.getLogger('ansible_base.jwt_consumer.views')


class PlatformUIRedirectView(AnsibleBaseDjangoAppApiView):
    authentication_classes = []
    permission_classes = (permissions.AllowAny,)
    metadata_class = None
    exception_class = exceptions.APIException

    name = _('Platform UI Redirect')

    def finalize_response(self, request, response, *args, **kwargs):
        url = get_setting("ANSIBLE_BASE_JWT_REDIRECT_URI", get_setting("ANSIBLE_BASE_JWT_KEY", None))
        service_type = get_setting("ANSIBLE_BASE_JWT_REDIRECT_TYPE", "unknown")
        if not url:
            return HttpResponseNotFound()

        url_parts = urlparse(url)
        base_url = urlunsplit((url_parts[0], url_parts[1], '', '', ''))
        context = Context({'redirect_url': base_url, 'service': service_type})
        try:
            filename = join(dirname(inspect.getfile(self.__class__)), 'redirect.html')
            with open(filename, 'r') as f:
                redirect_template = f.read()
        except Exception as e:
            logger.error(f"Failed to load redirect.html: {e}")
            return HttpResponseNotFound()

        template = Template(redirect_template)
        return HttpResponse(template.render(context))
