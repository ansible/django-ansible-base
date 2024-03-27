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

from ansible_base.authentication.models.authenticator import Authenticator
from ansible_base.lib.checks import check_charfield_has_max_length


def test_check_charfield_has_max_length_fails():
    with mock.patch.object(Authenticator._meta.get_field('type'), 'max_length', new=None):
        errors = check_charfield_has_max_length(None)
        assert len(errors) == 1
        assert errors[0].id == 'ansible_base.E001'
