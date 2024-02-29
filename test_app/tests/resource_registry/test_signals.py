from unittest import mock

import pytest

from test_app.models import EncryptionModel, Organization


@pytest.mark.django_db
def test_unregistered_model_triggers_no_save_signals():
    obj = EncryptionModel.objects.create()
    with mock.patch('ansible_base.resource_registry.models.Resource.update_from_content_object') as mck:
        obj.a = 'foobar'
        obj.save()
    mck.assert_not_called()


@pytest.mark.django_db
def test_unregistered_model_triggers_no_delete_signals():
    obj = EncryptionModel.objects.create()
    with mock.patch('ansible_base.resource_registry.models.Resource.delete') as mck:
        obj.delete()
    mck.assert_not_called()


@pytest.mark.django_db
def test_registered_model_triggers_save_signals():
    obj = Organization.objects.create(name='foo')
    with mock.patch('ansible_base.resource_registry.models.Resource.update_from_content_object') as mck:
        obj.description = 'foobar'
        obj.save()
    mck.assert_called_once_with()


@pytest.mark.django_db
def test_registered_model_triggers_delete_signals():
    obj = Organization.objects.create(name='foo')
    with mock.patch('ansible_base.resource_registry.models.Resource.delete') as mck:
        obj.delete()
    mck.assert_called_once_with()
