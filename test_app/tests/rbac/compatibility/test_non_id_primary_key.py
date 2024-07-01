import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition
from test_app.models import PositionModel


@pytest.fixture
def nk_rd():
    return RoleDefinition.objects.create_from_permissions(
        name='name-key-admin',
        permissions=['change_positionmodel', 'view_positionmodel', 'delete_positionmodel'],
        content_type=ContentType.objects.get_for_model(PositionModel),
    )


@pytest.fixture
def position(organization):
    return PositionModel.objects.create(position=4, organization=organization)


@pytest.mark.django_db
def test_give_user_permission(user, nk_rd, position):
    "Give user permission to model with a non-id primary key and do basic evaluations"
    assert not user.has_obj_perm(position, 'change')
    assert set(PositionModel.access_qs(user)) == set()

    nk_rd.give_permission(user, position)

    assert user.has_obj_perm(position, 'change')
    assert set(PositionModel.access_qs(user)) == set([position])


@pytest.mark.django_db
def test_make_non_id_api_assignment(admin_api_client, nk_rd, position, user):
    url = get_relative_url('roleuserassignment-list')
    data = dict(role_definition=nk_rd.id, user=user.id, content_type='aap.positionmodel', object_id=position.position)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data

    assert user.has_obj_perm(position, 'change')
    assert set(PositionModel.access_qs(user)) == set([position])
