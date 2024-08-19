import pytest
from django.apps import apps
from django.contrib.admin.models import LogEntry as AdminLogEntry

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac import permission_registry
from ansible_base.rbac.management import create_dab_permissions
from ansible_base.rbac.models import DABPermission
from test_app.models import LogEntry


def test_same_name_not_registered():
    assert permission_registry.is_registered(LogEntry)
    assert not permission_registry.is_registered(AdminLogEntry)


@pytest.mark.django_db
def test_does_not_create_unregistered_permission_entries():
    permission_ct = DABPermission.objects.count()
    # we should not have anything in the admin app registered
    create_dab_permissions(apps.get_app_config('admin'), apps=apps)
    assert permission_ct == DABPermission.objects.count()  # permission count did not change


@pytest.mark.django_db
def test_create_custom_role_name_conflict_model(admin_api_client):
    url = get_relative_url('roledefinition-list')
    data = dict(name='Single Log Entry Viewer', content_type='aap.logentry', permissions=['aap.view_logentry'])
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert 'id' in response.data, response.data
