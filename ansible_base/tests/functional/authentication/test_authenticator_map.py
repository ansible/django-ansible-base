import pytest
from django.urls import reverse


def test_authenticator_map_list_empty_by_default(admin_api_client):
    """
    Test that we can list authenticator maps. No maps are listed by default.
    """
    url = reverse("authenticator_map-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data == []


def test_authenticator_map_list(admin_api_client, local_authenticator_map):
    """
    Test that we can list authenticator maps, if they exist.
    """
    url = reverse("authenticator_map-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]['id'] == local_authenticator_map.id
    assert response.data[0]['triggers'] == local_authenticator_map.triggers


def test_authenticator_map_detail(admin_api_client, local_authenticator_map):
    """
    Test that we can get a single authenticator map.
    """
    url = reverse("authenticator_map-detail", kwargs={'pk': local_authenticator_map.id})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['id'] == local_authenticator_map.id
    assert response.data['triggers'] == local_authenticator_map.triggers


@pytest.mark.parametrize(
    'triggers',
    [
        {'always': {}},
        {'never': {}},
        {'groups': {'has_or': ['foobar-group']}},
        {'attributes': {'email': {'equals': 'foo@example.com'}}},
        {'attributes': {'email': {'in': ['foo@example.com', 'bar@example.com']}}},
    ],
)
def test_authenticator_map_create(admin_api_client, local_authenticator, triggers, shut_up_logging):
    """
    Test that we can create an authenticator map.
    """
    url = reverse("authenticator_map-list")
    data = {
        'name': 'Rule 3',
        'authenticator': local_authenticator.id,
        'map_type': 'is_superuser',
        'triggers': triggers,
        'organization': 'foobar-org',
        'team': 'foobar-team',
        'order': 1,
    }
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 201, response.data
    assert response.data['id'] == local_authenticator.id
    assert response.data['triggers'] == triggers
    assert response.data['map_type'] == 'is_superuser'


def test_authenticator_map_invalid_map_type(admin_api_client, local_authenticator, shut_up_logging):
    """
    Invalid map_type should be rejected.
    """
    url = reverse("authenticator_map-list")
    data = {
        'authenticator': local_authenticator.id,
        'map_type': 'invalid',
        'triggers': {'always': {}},
        'organization': 'foobar-org',
        'team': 'foobar-team',
        'order': 1,
    }
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 400, response.data
    assert '"invalid" is not a valid choice.' in response.data['map_type'][0]


@pytest.mark.parametrize(
    'map_type, params, error_field, error_message',
    [
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'team', 'triggers': {'always': {}}, 'order': 1, 'organization': 'foobar-org'},
            'team',
            'You must specify a team with the selected map type',
            id="map_type=team, missing team param",
        ),
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'team', 'triggers': {'always': {}}, 'order': 1, 'organization': 'foobar-org', 'team': None},
            'team',
            'You must specify a team with the selected map type',
            id="map_type=team, team param is None",
        ),
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'team', 'triggers': {'always': {}}, 'order': 1, 'organization': 'foobar-org', 'team': ''},
            'team',
            "This field may not be blank.",
            id="map_type=team, team param is empty string",
        ),
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'team', 'triggers': {'always': {}}, 'order': 1, 'team': 'foobar-team'},
            'organization',
            "You must specify an organization with the selected map type",
            id="map_type=team, missing organization param",
        ),
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'team', 'triggers': {'always': {}}, 'order': 1, 'team': 'foobar-team', 'organization': None},
            'organization',
            "You must specify an organization with the selected map type",
            id="map_type=team, organization param is None",
        ),
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'team', 'triggers': {'always': {}}, 'order': 1, 'team': 'foobar-team', 'organization': ''},
            'organization',
            "This field may not be blank.",
            id="map_type=team, organization param is empty string",
        ),
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'is_superuser', 'order': 1},
            'triggers',
            "Triggers must be a valid dict",
            id="map_type=is_superuser, missing triggers param",
        ),
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'is_superuser', 'triggers': {'always': {}}, 'order': "hey"},
            'order',
            "A valid integer is required.",
            id="map_type=is_superuser, order param is a non-digit string",
        ),
        pytest.param(
            'is_superuser',
            {'name': 'Rule 1', 'map_type': 'is_superuser', 'triggers': {'always': {}}},
            'order',
            "Must be a valid integer",
            id="map_type=is_superuser, missing order param",
        ),
    ],
)
def test_authenticator_map_validate(admin_api_client, local_authenticator, shut_up_logging, map_type, params, error_field, error_message):
    """
    Create invalid authenticator maps and ensure that they are rejected.
    """
    url = reverse("authenticator_map-list")
    data = {
        'authenticator': local_authenticator.id,
    }
    data.update(params)
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 400, response.data
    assert error_message in response.data[error_field]


@pytest.mark.parametrize(
    'triggers, error_field, error_message',
    [
        pytest.param(
            None,
            "triggers",
            "This field may not be null.",
            id="triggers is None",
        ),
        pytest.param(
            {},
            "triggers",
            "Triggers must be a valid dict",
            id="triggers is empty dict",
        ),
        pytest.param(
            {'invalid_key': {}},
            "triggers.invalid_key",
            "Invalid, can only be one of",
            id="triggers is dict with invalid key",
        ),
        pytest.param(
            {'always': 'not a dict'},
            "triggers.always",
            "Expected dict but got str",
            id="triggers always is invalid type",
        ),
        pytest.param(
            {'never': 'not a dict'},
            "triggers.never",
            "Expected dict but got str",
            id="triggers never is invalid type",
        ),
        pytest.param(
            {'groups': 'not a dict'},
            "triggers.groups",
            "Expected dict but got str",
            id="triggers groups is invalid type",
        ),
        pytest.param(
            {'attributes': 'not a dict'},
            "triggers.attributes",
            "Expected dict but got str",
            id="triggers attributes is invalid type",
        ),
        pytest.param(
            {'attributes': {"email": {"equals": "foo@example.com"}, "join_condition": True}},
            "triggers.attributes.join_condition",
            "Expected str but got bool",
            id="triggers attributes join condition is invalid type (recursive validation)",
        ),
        pytest.param(
            {'attributes': {"email": {"invalid_predicate": "foo@example.com"}, "join_condition": "and"}},
            "triggers.attributes.email.invalid_predicate",
            "Invalid, can only be one of",
            id="triggers attributes invalid predicate is supplied (recursive validation)",
        ),
        pytest.param(
            {'attributes': {"email": {"equals": "foo@example.com"}, "join_condition": "invalid"}},
            "triggers.attributes.join_condition",
            "Invalid, choices can only be one of",
            id="triggers attributes invalid join condition is supplied",
        ),
        pytest.param(
            {'groups': {"has_or": [1, 2]}},
            "triggers.groups.has_or.1",
            "Invalid, must be of type str",
            id="triggers groups has_or has invalid type elements (int)",
        ),
        pytest.param(
            {'groups': {"has_or": [True]}},
            "triggers.groups.has_or.True",
            "Invalid, must be of type str",
            id="triggers groups has_or has invalid type elements (bool)",
        ),
        pytest.param(
            {'groups': {"has_or": [None]}},
            "triggers.groups.has_or.None",
            "Invalid, must be of type str",
            id="triggers groups has_or has invalid type elements (None)",
        ),
        pytest.param(
            {'groups': {"has_or": "seven"}},
            "triggers.groups.has_or",
            "Expected list but got str",
            id="triggers groups has_or is not list",
        ),
        pytest.param(
            {'groups': 1337},
            "triggers.groups",
            "Expected dict but got int",
            id="triggers groups is not dict",
        ),
    ],
)
def test_authenticator_map_validate_trigger_data(admin_api_client, local_authenticator, shut_up_logging, triggers, error_field, error_message):
    """
    Test trigger validation for authenticator maps.
    """
    url = reverse("authenticator_map-list")
    data = {
        'name': 'Rule 2',
        'triggers': triggers,
        'map_type': 'is_superuser',
        'order': 1,
        'authenticator': local_authenticator.id,
    }
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 400, response.data
    assert error_message in response.data[error_field][0]


def test_required_fields():
    # TODO: Check to make sure that the org/team are required for a team map, org is required for an org
    assert True


def test_unique_names():
    # TODO: Check to make sure that authenticator names can be the same with different authenticators but not the same within a single authenticator
    assert True
