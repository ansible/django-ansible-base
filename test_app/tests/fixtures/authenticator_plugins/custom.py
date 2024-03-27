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

from django.contrib.auth import get_user_model

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin

logger = logging.getLogger('test_app.tests.fixtures.authenticator_plugins.custom')


class AuthenticatorPlugin(AbstractAuthenticatorPlugin):
    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(database_instance, *args, **kwargs)
        self.configuration_encrypted_fields = []
        self.type = "custom"
        self.set_logger(logger)
        self.category = "password"

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username == "admin" and password == "hello123":
            user = get_user_model().objects.get(username=username)
            return user

        return None
