import pytest
from django.apps import apps
from django.contrib.admin.models import LogEntry as AdminLogEntry

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
