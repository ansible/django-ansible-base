import uuid

import pytest

from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition, RoleUserAssignment
from ansible_base.rbac.remote import RemoteObject
from test_app.models import User


@pytest.mark.django_db
def test_give_remote_permission(rando, foo_type, foo_permission, foo_rd):
    "Test for a few technical elements related to giving permission to remote objects, and using in query."
    assert foo_type.service == 'foo'  # a place, a domain, a server, known as foo
    assert foo_type.api_slug == 'foo.foo'  # there lives a foo in foo

    assert foo_permission.api_slug == 'foo.foo_foo'  # expression of the ability that one may foo a foo

    a_foo = RemoteObject(content_type=foo_type, object_id=42)
    assignment = foo_rd.give_permission(rando, a_foo)
    assert '42' in repr(a_foo)
    assert a_foo.pk == 42

    assignment = RoleUserAssignment.objects.get(pk=assignment.pk)
    assert assignment.content_object.pk == 42
    assert isinstance(assignment.content_object, RemoteObject)
    assert isinstance(assignment.content_object, RemoteObject)  # There was a bug where multiple references would error

    # We can do evaluation querysets, but these can not return objects, just id values
    assert set(foo_type.model_class().access_ids_qs(actor=rando, codename='foo')) == {(int(assignment.object_id),)}

    # Test that user-attached methods also work
    assert rando.has_obj_perm(a_foo, 'foo')
    with pytest.raises(RuntimeError) as exc:
        assert not rando.has_obj_perm(a_foo, 'bar')  # not a valid permission
    assert 'The permission bar_foo is not valid for model foo' in str(exc)


@pytest.mark.django_db
def test_prefetch_related_objects(django_assert_num_queries, foo_type, foo_type_uuid, foo_rd, foo_rd_uuid, inv_rd, inventory):
    users = [User.objects.create(username=f'user{i}') for i in range(10)]

    a_foo = RemoteObject(content_type=foo_type, object_id=42)
    a_foo_uuid = RemoteObject(content_type=foo_type_uuid, object_id=str(uuid.uuid4()))
    for u in users:
        foo_rd.give_permission(u, a_foo)
        foo_rd_uuid.give_permission(u, a_foo_uuid)
        inv_rd.give_permission(u, inventory)

    assert RoleUserAssignment.objects.count() == 10 * 3
    for _ in range(2):
        with django_assert_num_queries(11):
            assert {assignment.content_object for assignment in RoleUserAssignment.objects.all()} == {a_foo, inventory, a_foo_uuid}
    for _ in range(2):
        with django_assert_num_queries(2):
            assert {assignment.content_object for assignment in RoleUserAssignment.objects.prefetch_related('content_object')} == {a_foo, inventory, a_foo_uuid}


@pytest.mark.django_db
def test_organization_permission_remote_object(rando, foo_type, organization):
    """If the remote object is a child of a shared organization object, org roles should evaluate that users have permission

    This is supported by loading a reference to the parent in the RemoteObject.
    """
    permissions = []
    for codename in ('view_foo', 'change_foo', 'foo_foo'):
        permissions.append(DABPermission.objects.create(codename=codename, content_type=foo_type))
    view_foo_rd = RoleDefinition.objects.create_from_permissions(
        name='Foo fooers for the foos in foo service', permissions=[permissions[0].api_slug], content_type=foo_type
    )
    a_foo = RemoteObject(content_type=foo_type, object_id=42, parent_reference=organization.pk)
    assignment = view_foo_rd.give_permission(rando, a_foo)
    assert str(assignment.object_role.parent_reference) == str(organization.pk)
    assert not rando.has_obj_perm(a_foo, 'change_foo')

    org_ct = DABContentType.objects.get_for_model(organization)
    org_foo_rd = RoleDefinition.objects.create_from_permissions(
        name='Org level foo role', permissions=['view_foo', 'change_foo', 'foo_foo', 'shared.view_organization'], content_type=org_ct
    )
    org_foo_rd.give_permission(rando, organization)

    assert rando.has_obj_perm(a_foo, 'foo')


@pytest.mark.django_db
def test_object_roles_same_type_different_service(rando):
    cts = {}
    rds = {}
    foos = {}
    for service_name in ('barland', 'fooland'):
        # same-named model in both services
        ct = DABContentType.objects.create(service=service_name, model='foo', app_label='foo')
        cts[service_name] = ct
        permissions = []
        for codename in ('view_foo', 'change_foo', 'foo_foo'):
            permissions.append(DABPermission.objects.create(codename=codename, content_type=ct))
        # NOTE: obviously we have to use the full api_slug of permission, as codename would be ambiguous
        rd = RoleDefinition.objects.create_from_permissions(
            name=f'The foo role for {service_name} service', permissions=[perm.api_slug for perm in permissions], content_type=ct
        )
        rds[service_name] = rd
        foos[service_name] = RemoteObject(content_type=ct, object_id=4)

    for service_name in ('barland', 'fooland'):
        # Nothing assigned yet, rando has no permission to fooland or barland
        assert [rando.has_obj_perm(foos[this_service_name], 'change') for this_service_name in ('barland', 'fooland')] == [False, False]

        rds[service_name].give_permission(rando, foos[service_name])

        # Just has permission to either fooland or barland, according to loop
        assert [rando.has_obj_perm(foos[this_service_name], 'change') for this_service_name in ('barland', 'fooland')] == [
            bool(this_service_name == service_name) for this_service_name in ('barland', 'fooland')
        ]

        rds[service_name].remove_permission(rando, foos[service_name])


@pytest.mark.django_db
def test_org_roles_same_type_different_service(rando, organization):
    org_ct = DABContentType.objects.get_for_model(organization)
    cts = {}
    rds = {}
    foos = {}
    for service_name in ('barland', 'fooland'):
        ct = DABContentType.objects.create(service=service_name, model='foo', app_label='foo', parent_content_type=org_ct)
        cts[service_name] = ct
        permissions = []
        for codename in ('view_foo', 'change_foo', 'foo_foo'):
            permissions.append(DABPermission.objects.create(codename=codename, content_type=ct))

        rd = RoleDefinition.objects.create_from_permissions(
            name=f'The organization-level foo role for {service_name} service',
            permissions=[perm.api_slug for perm in permissions],
            content_type=org_ct,  # difference from last test
        )
        obj_rd = RoleDefinition.objects.create_from_permissions(
            name=f'Object-level view permission for {service_name} service', permissions=[f'{service_name}.view_foo'], content_type=ct
        )
        rds[service_name] = rd
        foos[service_name] = RemoteObject(content_type=ct, object_id=4, parent_reference=organization.pk)
        obj_rd.give_permission(rando, foos[service_name])

    for service_name in ('barland', 'fooland'):
        assert [rando.has_obj_perm(foos[this_service_name], 'change') for this_service_name in ('barland', 'fooland')] == [False, False]

        rds[service_name].give_permission(rando, organization)

        # Has permission to either fooland or barland stuff via organization
        assert [rando.has_obj_perm(foos[this_service_name], 'change') for this_service_name in ('barland', 'fooland')] == [
            bool(this_service_name == service_name) for this_service_name in ('barland', 'fooland')
        ], f'User should have permission to exactly {service_name} resource'

        rds[service_name].remove_permission(rando, organization)
