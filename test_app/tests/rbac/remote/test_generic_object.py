from unittest import mock

import pytest

from ansible_base.rbac import triggers
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.remote import GenericObject, RemoteObject
from test_app.models import Inventory, Organization


@pytest.mark.django_db
@pytest.mark.parametrize('other_id, equal', [(42, True), (43, False)])
def test_remote_object_compares_as_generic_object(foo_type, other_id, equal):
    remote = RemoteObject(content_type=foo_type, object_id=42)
    generic = GenericObject(foo_type.id, other_id)
    assert (remote == generic) is equal
    assert (generic == remote) is equal
    assert (hash(remote) == hash(generic)) is equal


@pytest.mark.django_db
def test_created_object_look_ahead_passes_parent_chain(rando, organization, org_inv_rd):
    org_inv_rd.give_permission(rando, organization)
    with mock.patch.object(triggers, 'recompute_role_evaluations_for_created', wraps=triggers.recompute_role_evaluations_for_created) as spy:
        inv = Inventory.objects.create(name='look-ahead', organization=organization)
    content_types = permission_registry.content_type_model.objects
    assert spy.call_args.kwargs['look_ahead'] == GenericObject(content_types.get_for_model(Inventory).id, inv.pk)
    assert spy.call_args.kwargs['target_parents'] == [GenericObject(content_types.get_for_model(Organization).id, organization.pk)]
