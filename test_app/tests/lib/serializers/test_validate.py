import pytest
from django.urls import reverse

authenticator_data = {
    "name": "Local Database Authenticator",
    "enabled": True,
    "create_objects": True,
    "remove_users": False,
    "configuration": {},
    "type": "ansible_base.authentication.authenticator_plugins.local",
    "order": 1,
}


@pytest.mark.parametrize(
    "reverse_name,method,query_params,same_name,configuration,response_code,response_body",
    [
        ("authenticator-detail", "put", "", True, {}, 200, None),
        ("authenticator-detail", "put", "validate=False", True, {}, 200, None),
        ("authenticator-detail", "put", "validate=True", True, {}, 202, None),
        ("authenticator-detail", "put", "validate=False", True, {"a": "b"}, 400, {'a': ['a is not a supported configuration option.']}),
        ("authenticator-detail", "put", "validate=True", True, {"a": "b"}, 400, {'a': ['a is not a supported configuration option.']}),
        ("authenticator-list", "post", "validate=True", False, {"a": "b"}, 400, {'a': ['a is not a supported configuration option.']}),
        ("authenticator-list", "post", "validate=True", True, {}, 400, None),
        ("authenticator-list", "post", "validate=False", False, {"a": "b"}, 400, {'a': ['a is not a supported configuration option.']}),
        ("authenticator-list", "post", "validate=False", True, {}, 400, None),
        ("authenticator-list", "post", "validate=True", False, {}, 202, None),
        ("authenticator-detail", "patch", "", True, {}, 200, None),
        ("authenticator-detail", "patch", "validate=False", True, {}, 200, None),
        ("authenticator-detail", "patch", "validate=True", True, {}, 202, None),
        ("authenticator-detail", "patch", "validate=False", True, {"a": "b"}, 400, {'a': ['a is not a supported configuration option.']}),
        ("authenticator-detail", "patch", "validate=True", True, {"a": "b"}, 400, {'a': ['a is not a supported configuration option.']}),
        ("authenticator-detail", "put", "validate=False&validate=True", True, {}, 202, None),
        ("authenticator-detail", "put", "validate=False&validate=False", True, {}, 200, None),
        ("authenticator-detail", "put", "validate=True&validate=True", True, {}, 202, None),
        ("authenticator-detail", "put", "validate=True&validate=False", True, {}, 200, None),
    ],
    ids=[
        'Good put implicit no validation',
        'Good put no validation',
        'Good put validation',
        'Bad put no validation',
        'Bad put validation',
        'Bad post (serializer issue) with validation',
        'Bad post (db issue) validation',
        'Bad post (serializer issue) with no validation',
        'Bad post (db issue) with no validation',
        'Good post with validation',
        'Good patch implicit no validation',
        'Good patch no validation',
        'Good patch validation',
        'Bad patch no validation',
        'Bad patch validation',
        'Good put multiple validation = True',
        'Good put multiple validation = False',
        'Good put multiple validation = True',
        'Good put multiple validation = False',
    ],
)
def test_validation_mixin_validate(
    local_authenticator, admin_api_client, reverse_name, method, query_params, same_name, configuration, response_code, response_body
):
    if reverse_name == 'authenticator-detail':
        url = reverse(reverse_name, kwargs={'pk': local_authenticator.pk})
    else:
        url = reverse(reverse_name)

    if query_params:
        url = f'{url}?{query_params}'

    authenticator_data['configuration'] = configuration
    if same_name:
        authenticator_data['name'] = local_authenticator.name
    else:
        authenticator_data['name'] = 'Not the local authenticator name'

    response = getattr(admin_api_client, method)(url, data=authenticator_data, format='json')
    assert response.status_code == response_code, f'Expected {response_code} got {response.status_code} {url} {response.json()}'
    if response_body:
        assert response.json() == response_body
