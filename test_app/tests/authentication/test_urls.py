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

import importlib

import pytest
from django.test.utils import override_settings


@pytest.mark.parametrize(
    'setting',
    (
        (None),
        ('junk'),
        ('ansible_base.authentication.views'),
        ('ansible_base.authentication.views.AuthenticatorViewSet'),
    ),
)
def test_authentication_urls_setting(setting):
    from ansible_base.authentication import urls

    with override_settings(ANSIBLE_BASE_USER_VIEWSET=setting):
        importlib.reload(urls)
