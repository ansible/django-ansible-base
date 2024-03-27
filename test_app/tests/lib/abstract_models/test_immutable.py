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

import pytest
from crum import impersonate

from test_app.models import ImmutableLogEntry, ImmutableLogEntryNotCommon


@pytest.mark.django_db
@pytest.mark.parametrize('model', [ImmutableLogEntry, ImmutableLogEntryNotCommon])
def test_immutable_model_is_immutable(system_user, model):
    """
    ImmutableModel prevents saves from happening after the first save.
    """
    log_entry = model.objects.create(message="Oh no! An important message!")
    log_entry.message = "Oh no! An even more important message!"

    with pytest.raises(ValueError) as excinfo:
        log_entry.save()
    assert excinfo.value.args[0] == f"{model.__name__} is immutable and cannot be modified."

    # Ensure that nothing got updated before the exception was raised
    log_entry.refresh_from_db()
    assert log_entry.message == "Oh no! An important message!"


@pytest.mark.django_db
def test_immutable_model_has_no_modified_fields():
    """
    After ImmutableCommonModel should never have a modified/modified_by field.
    """
    instance = ImmutableLogEntry(message="Oh no! An important message!")

    instance.save()

    with pytest.raises(AttributeError):
        instance.modified

    with pytest.raises(AttributeError):
        instance.modified_by


def test_immutable_model_common_created_by(user):
    """
    ImmutableCommonModel should have a created_by field.
    """
    with impersonate(user):
        instance = ImmutableLogEntry(message="Oh no! An important message!")
        instance.save()

    assert instance.created_by == user


def test_immutable_model_created_by(user):
    """
    ImmutableModel should NOT have a created_by field.
    """
    with impersonate(user):
        instance = ImmutableLogEntryNotCommon(message="Oh no! An important message!")
        instance.save()

    with pytest.raises(AttributeError):
        instance.created_by
