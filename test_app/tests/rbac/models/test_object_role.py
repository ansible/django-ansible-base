from unittest import mock

import pytest

from ansible_base.rbac.models import ObjectRole
from test_app.models import User


@pytest.mark.django_db
def test_existing_object_role_race(inv_rd, inventory):
    user1 = User.objects.create(username='user1')
    inv_rd.give_permission(user1, inventory)

    user2 = User.objects.create(username='user2')
    with mock.patch('django.db.models.query.QuerySet.first', return_value=None):
        assert ObjectRole.objects.filter(object_id=inventory.pk).first() is None  # sanity
        inv_rd.give_permission(user2, inventory)
    assert user2.has_obj_perm(inventory, 'change')
