import pytest

from ansible_base.rbac.policies import can_change_user
from test_app.models import User


@pytest.mark.django_db
def test_org_admin_can_not_change_superuser(org_admin_rd, organization):
    org_admin = User.objects.create(username='org-admin')
    org_admin_rd.give_permission(org_admin, organization)

    admin = User.objects.create(username='new-superuser', is_superuser=True)
    assert not can_change_user(org_admin, admin)


@pytest.mark.django_db
def test_unrelated_can_not_change_user():
    alice = User.objects.create(username='alice')
    bob = User.objects.create(username='bob')

    for first, second in [(alice, bob), (bob, alice)]:
        assert not can_change_user(first, second)


@pytest.mark.django_db
def test_superuser_can_change_new_user(admin_user):
    alice = User.objects.create(username='alice')
    assert can_change_user(admin_user, alice)


@pytest.mark.django_db
def test_user_can_manage_themselves():
    alice = User.objects.create(username='alice')
    assert can_change_user(alice, alice)
