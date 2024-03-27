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

from unittest import mock

import pytest

from ansible_base.authentication.models import Authenticator


@pytest.mark.django_db
def test_authenticator_from_db(ldap_authenticator):
    ldap_auth = Authenticator.objects.first()
    # Validate that we got the proper password when loading the object the first time
    assert ldap_auth.configuration.get('BIND_PASSWORD', None) == 'securepassword'
    with mock.patch('ansible_base.authentication.models.authenticator.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        ldap_auth = Authenticator.objects.first()
        assert ldap_auth.configuration.get('BIND_PASSWORD', None) != 'securepassword'
