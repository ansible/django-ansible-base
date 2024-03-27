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

from rest_framework.response import Response

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class, get_authenticator_plugins
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class AuthenticatorPluginView(AnsibleBaseDjangoAppApiView):
    def get(self, request, format=None):
        plugins = get_authenticator_plugins()
        resp = {"authenticators": []}

        for p in plugins:
            try:
                klass = get_authenticator_class(p)
                config = klass.configuration_class()
                config_schema = config.get_configuration_schema()
                resp['authenticators'].append(
                    {"type": p, "configuration_schema": config_schema, "documentation_url": getattr(config, "documentation_url", None)}
                )
            except ImportError as ie:
                # If we got an import error its already logged and we can move on
                if 'errors' not in resp:
                    resp['errors'] = []
                resp['errors'].append(ie.__str__())

        resp['authenticators'] = sorted(resp['authenticators'], key=lambda k: k['type'])

        return Response(resp)
