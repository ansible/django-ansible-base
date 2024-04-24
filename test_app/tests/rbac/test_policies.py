import pytest

from ansible_base.rbac.policies import can_change_user
from test_app.models import User


@pytest.mark.django_db
def test_org_admin_can_not_change_superuser(org_admin_rd, organization):
    org_admin = User.objects.create(username='org-admin')
    org_admin_rd.give_permission(org_admin, organization)

    admin = User.objects.create(username='new-superuser', is_superuser=True)
    assert not can_change_user(org_admin, admin)
