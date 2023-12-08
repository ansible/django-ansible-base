import pytest
from django.contrib.auth.models import Permission

from test_app.models import Inventory, ProxyInventory


@pytest.mark.django_db
def test_inventory_permissions_duplicated():
    "This assures that test_app has more than one model with the same permission"
    view_inv_perms = Permission.objects.filter(codename='view_inventory')
    assert view_inv_perms.count() == 2
    assert set(perm.content_type.model_class() for perm in view_inv_perms) == set([Inventory, ProxyInventory])
