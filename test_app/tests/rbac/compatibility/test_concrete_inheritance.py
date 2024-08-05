import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.rbac.models import RoleDefinition
from test_app.models import AutoExtraUUIDModel, ExtraExtraUUIDModel, ManualExtraUUIDModel


@pytest.fixture
def auto_uuid_obj(organization):
    return AutoExtraUUIDModel.objects.create(organization=organization)


@pytest.fixture
def manual_uuid_obj(uuid_obj):
    return ManualExtraUUIDModel.objects.create(uuidmodel_ptr=uuid_obj)


@pytest.fixture
def extra_extra_uuid_obj(manual_uuid_obj):
    return ExtraExtraUUIDModel.objects.create(extra_uuid=manual_uuid_obj)


def _make_rd(cls):
    cls_name = cls._meta.model_name
    return RoleDefinition.objects.create_from_permissions(
        name='object admin for extra UUID model',
        permissions=[f'change_{cls_name}', f'view_{cls_name}', f'delete_{cls_name}'],
        content_type=ContentType.objects.get_for_model(cls),
    )


@pytest.fixture
def auto_obj_rd():
    return _make_rd(AutoExtraUUIDModel)


@pytest.fixture
def manual_obj_rd():
    return _make_rd(ManualExtraUUIDModel)


@pytest.fixture
def extra_uuid_obj_rd():
    return _make_rd(ExtraExtraUUIDModel)


@pytest.mark.django_db
def test_give_user_object_permission_auto_obj(auto_obj_rd, auto_uuid_obj, user):
    assert not user.has_obj_perm(auto_uuid_obj, 'change')
    assert set(AutoExtraUUIDModel.access_qs(user)) == set()

    auto_obj_rd.give_permission(user, auto_uuid_obj)

    assert user.has_obj_perm(auto_uuid_obj, 'change')
    assert set(AutoExtraUUIDModel.access_qs(user)) == set([auto_uuid_obj])


@pytest.mark.django_db
def test_give_user_object_permission_manual_obj(manual_obj_rd, manual_uuid_obj, user):
    assert not user.has_obj_perm(manual_uuid_obj, 'change')
    assert set(ManualExtraUUIDModel.access_qs(user)) == set()

    manual_obj_rd.give_permission(user, manual_uuid_obj)

    assert user.has_obj_perm(manual_uuid_obj, 'change')
    assert set(ManualExtraUUIDModel.access_qs(user)) == set([manual_uuid_obj])


@pytest.mark.django_db
def test_give_user_object_permission_extra_extra_uuid_obj(extra_uuid_obj_rd, extra_extra_uuid_obj, user):
    assert not user.has_obj_perm(extra_extra_uuid_obj, 'change')
    assert set(ExtraExtraUUIDModel.access_qs(user)) == set()

    extra_uuid_obj_rd.give_permission(user, extra_extra_uuid_obj)

    assert user.has_obj_perm(extra_extra_uuid_obj, 'change')
    assert set(ExtraExtraUUIDModel.access_qs(user)) == set([extra_extra_uuid_obj])


@pytest.mark.django_db
def test_delete_with_permissions_auto_obj(auto_obj_rd, auto_uuid_obj, user):
    "Should not lead to an error"
    auto_obj_rd.give_permission(user, auto_uuid_obj)
    auto_uuid_obj.delete()


@pytest.mark.django_db
def test_delete_with_permissions_manual_obj(manual_obj_rd, manual_uuid_obj, user):
    "Should not lead to an error"
    manual_obj_rd.give_permission(user, manual_uuid_obj)
    manual_uuid_obj.delete()


@pytest.mark.django_db
def test_delete_with_permissions_nested_obj(extra_uuid_obj_rd, extra_extra_uuid_obj, user):
    "Should not lead to an error"
    extra_uuid_obj_rd.give_permission(user, extra_extra_uuid_obj)
    extra_extra_uuid_obj.delete()


@pytest.mark.django_db
def test_delete_org_with_permissions(auto_obj_rd, auto_uuid_obj, user):
    "Should not lead to an error"
    auto_obj_rd.give_permission(user, auto_uuid_obj)
    auto_uuid_obj.organization.delete()


@pytest.mark.django_db
def test_delete_with_permissions_parent_obj(uuid_rd, auto_uuid_obj, user):
    "Should not lead to an error"
    obj = auto_uuid_obj.uuidmodel_ptr
    uuid_rd.give_permission(user, obj)
    obj.delete()


# @pytest.mark.django_db
# def test_make_non_id_api_assignment(admin_api_client, nk_rd, position, user):
#     url = get_relative_url('roleuserassignment-list')
#     data = dict(role_definition=nk_rd.id, user=user.id, content_type='aap.positionmodel', object_id=position.position)
#     response = admin_api_client.post(url, data=data, format="json")
#     assert response.status_code == 201, response.data

#     assert user.has_obj_perm(position, 'change')
#     assert set(PositionModel.access_qs(user)) == set([position])
