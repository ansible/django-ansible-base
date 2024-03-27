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

from django.contrib.auth import BACKEND_SESSION_KEY
from django.core.exceptions import ImproperlyConfigured
from django.utils.deprecation import MiddlewareMixin

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugins


def get_authenticator_module_paths() -> list:
    plugins = get_authenticator_plugins()
    plugins = [f'{name}.AuthenticatorPlugin' for name in plugins]
    return plugins


class AuthenticatorBackendMiddleware(MiddlewareMixin):
    _plugins = None

    @property
    def plugins(self):
        if not self._plugins:
            self._plugins = get_authenticator_module_paths()
        return self._plugins

    def process_request(self, request):
        if not hasattr(request, "session"):
            raise ImproperlyConfigured(
                "The Django AuthenticatorBackendMiddleware requires session "
                "middleware to be installed. Edit your MIDDLEWARE setting to "
                "insert "
                "'django.contrib.sessions.middleware.SessionMiddleware' before "
                "'AuthenticatorBackendMiddleware'."
            )

        # If the session backend is one from one of the Authenticator plugins, change it to
        # ansible_base.authentication.backend.AnsibleBaseAuth so that the user can be logged
        # in since the Authenticator backends aren't in AUTHENTICATION_BACKENDS
        if backend := request.session.get(BACKEND_SESSION_KEY, None):
            if backend in self.plugins:
                request.session[BACKEND_SESSION_KEY] = "ansible_base.authentication.backend.AnsibleBaseAuth"
