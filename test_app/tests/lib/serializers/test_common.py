import pytest
from crum import impersonate

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.lib.serializers.common import CommonModelSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from test_app.models import EncryptionModel, ResourceMigrationTestModel, Team
from test_app.serializers import EncryptionModelSerializer, ResourceMigrationTestModelSerializer, TeamSerializer


@pytest.mark.django_db
def test_representation_of_encrypted_fields():
    model = EncryptionModel.objects.create()
    serializer = EncryptionModelSerializer()
    response = serializer.to_representation(model)
    assert response['testing1'] == ENCRYPTED_STRING
    assert response['testing2'] == ENCRYPTED_STRING


@pytest.mark.django_db
def test_update_of_encrypted_fields():
    model = EncryptionModel.objects.create()
    updated_data = {'testing1': 'c', 'testing2': ENCRYPTED_STRING}
    serializer = EncryptionModelSerializer()
    serializer.update(model, updated_data)
    updated_model = EncryptionModel.objects.first()
    assert updated_model.testing1 == 'c'
    assert updated_model.testing2 == EncryptionModel.testing2.field.default


def test_related_of_none():
    serializer = CommonModelSerializer()
    assert serializer._get_related(None) == {}


@pytest.mark.django_db
def test_related_of_model_with_related(ldap_authenticator):
    model = AuthenticatorMap.objects.create(
        authenticator=ldap_authenticator,
        map_type='always',
    )
    serializer = CommonModelSerializer()
    related = serializer._get_related(model)
    assert 'authenticator' in related and related['authenticator'] == f'/api/v1/authenticators/{ldap_authenticator.id}/'


@pytest.mark.django_db
def test_related_of_model_with_no_related(ldap_authenticator):
    model = EncryptionModel()
    serializer = CommonModelSerializer()
    assert serializer._get_related(model) == {}


@pytest.mark.django_db
def test_no_reverse_url_name():
    model = ResourceMigrationTestModel.objects.create()
    serializer = ResourceMigrationTestModelSerializer()
    assert serializer.get_url(model) == ''


@pytest.mark.django_db
def test_encrypted_model_reverse_url_name():
    model = EncryptionModel.objects.create()
    serializer = EncryptionModelSerializer()
    assert serializer.get_url(model) == f'/api/v1/encrypted_models/{model.pk}/'


def test_summary_of_none():
    serializer = CommonModelSerializer()
    assert serializer._get_summary_fields(None) == {}


@pytest.mark.django_db
def test_summary_of_model_with_no_summary(ldap_authenticator):
    model = EncryptionModel()
    serializer = CommonModelSerializer()
    assert serializer._get_summary_fields(model) == {}


@pytest.mark.django_db
def test_summary_of_model_with_summary(ldap_authenticator):
    model = AuthenticatorMap.objects.create(
        authenticator=ldap_authenticator,
        map_type='always',
    )
    serializer = CommonModelSerializer()
    summary = serializer._get_summary_fields(model)
    assert 'authenticator' in summary and summary['authenticator'] == {'id': ldap_authenticator.id, 'name': ldap_authenticator.name}


@pytest.mark.django_db
def test_summary_of_model_with_created_user(user, ldap_authenticator):
    with impersonate(user):
        model = AuthenticatorMap.objects.create(
            authenticator=ldap_authenticator,
            map_type='always',
        )
    assert model.created_by == user
    serializer = CommonModelSerializer()

    summary_fields = serializer._get_summary_fields(model)
    expected_summary = {'username': user.username, 'first_name': user.first_name, 'last_name': user.last_name, 'id': user.id}
    assert summary_fields['created_by'] == expected_summary
    assert summary_fields['modified_by'] == expected_summary

    assert serializer._get_related(model) == {
        'authenticator': f'/api/v1/authenticators/{ldap_authenticator.pk}/',
        'created_by': f'/api/v1/users/{user.pk}/',
        'modified_by': f'/api/v1/users/{user.pk}/',
    }


@pytest.mark.django_db
def test_summary_of_model_with_custom_reverse(user, organization):
    team = Team.objects.create(
        name='foo-team', encryptioner=EncryptionModel.objects.create(name='iamencrypted', testing1='foo', testing2='bar'), organization=organization
    )
    serializer = TeamSerializer()

    assert serializer._get_summary_fields(team)['encryptioner'] == {'id': team.encryptioner_id, 'name': 'iamencrypted'}

    assert serializer._get_related(team)['encryptioner'] == f'/api/v1/encrypted_models/{team.encryptioner_id}/'


@pytest.mark.django_db
def test_common_serializer_schema(openapi_schema):
    rd_schema = openapi_schema['components']['schemas']['RoleDefinitionDetail']
    for field_name in ('related', 'summary_fields'):
        assert rd_schema['properties'][field_name]['type'] == 'object'
        assert rd_schema['properties'][field_name]['readOnly'] is True

    for field_name in ('url', 'created'):
        assert rd_schema['properties'][field_name]['type'] == 'string'
        assert rd_schema['properties'][field_name]['readOnly'] is True
    assert rd_schema['properties']['created']['format'] == 'date-time'

    assert rd_schema['properties']['id']['type'] == 'integer'
    assert rd_schema['properties']['id']['readOnly'] is True
