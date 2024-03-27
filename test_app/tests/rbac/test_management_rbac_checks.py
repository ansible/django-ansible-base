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

from io import StringIO

import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.rbac.management.commands.RBAC_checks import Command
from ansible_base.rbac.models import ObjectRole, RoleDefinition
from test_app.models import Inventory


def run_and_get_output():
    cmd = Command()
    cmd.stdout = StringIO()
    cmd.handle()
    return cmd.stdout.getvalue()


@pytest.mark.django_db
def test_successful_no_data():
    assert "checking for up-to-date role evaluations" in run_and_get_output()


@pytest.mark.django_db
def test_role_definition_wrong_model(organization):
    inventory = Inventory.objects.create(name='foo-inv', organization=organization)
    rd, _ = RoleDefinition.objects.get_or_create(name='foo-def', permissions=['view_organization'])
    orole = ObjectRole.objects.create(object_id=inventory.id, content_type=ContentType.objects.get_for_model(inventory), role_definition=rd)
    assert f"Object role {orole} has permission view_organization for an unlike content type" in run_and_get_output()
