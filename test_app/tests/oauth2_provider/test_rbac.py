"""
This module tests RBAC against OAuth2 views and models.
The exact set of expected access comes directly from awx.main.access
and the doc strings of the relevant classes defined there are directly turned
into tests here.

Some of these tests might be redundant with other tests defined elsewhere.
This is intentional as this module is meant to check every single condition
defined within the AWX spec (as well as additional cases where the access
conditions are not met).
"""

import pytest
from django.urls import reverse

from ansible_base.oauth2_provider.models import OAuth2AccessToken
from ansible_base.rbac.models import RoleDefinition


@pytest.mark.parametrize(
    'user_case, has_access',
    [
        ('superuser', True),
        pytest.param('admin_of_app_user_org', True, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        pytest.param('user_in_org', True, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        ('user', False),
        ('anon', False),
    ],
)
@pytest.mark.django_db
def test_oauth2_application_read_change_delete(
    request, user_case, has_access, org_member_rd, org_admin_rd, random_user, oauth2_application, organization, unauthenticated_api_client
):
    """
    From awx.main.access.OAuth2ApplicationAccess:

    I can read, change or delete OAuth 2 applications when:
     - I am a superuser.
     - I am the admin of the organization of the user of the application.
     - I am a user in the organization of the application.
    """
    app = oauth2_application[0]
    app.organization = organization
    app.user = random_user
    app.save()

    expected_read_status = 200 if has_access else 403
    expected_change_status = 200 if has_access else 403
    expected_delete_status = 204 if has_access else 403

    # Determine the user based on the test case (adding them to organizations, etc. as necessary).
    if user_case == 'superuser':
        # - I am a superuser.
        user = request.getfixturevalue('admin_user')  # Nothing to do, just use the admin user
    else:
        user = request.getfixturevalue('random_user_1')
        second_org = request.getfixturevalue('organization_1')
        if user_case == 'admin_of_app_user_org':
            # - I am the admin of the organization of the user of the application.
            RoleDefinition.objects.managed.org_admin.give_permission(user, second_org)  # And make me an admin of the org
            RoleDefinition.objects.managed.org_member.give_permission(app.user, second_org)  # Add the app owner user to the org
        elif user_case == 'user_in_org':
            # - I am a user in the organization of the application.
            RoleDefinition.objects.managed.org_member.give_permission(user, organization)  # Add me to the org
        elif user_case == 'user':
            # Negative case, do nothing, the user is just some random user
            pass
        elif user_case == 'anon':
            user = None
            expected_read_status = 401
            expected_change_status = 401
            expected_delete_status = 401
        else:
            raise ValueError(f"Invalid user_case: {user_case}")

    if user is not None:
        unauthenticated_api_client.force_login(user)
    url = reverse("application-detail", args=[app.id])

    # Read
    response = unauthenticated_api_client.get(url)
    assert response.status_code == expected_read_status, (response.status_code, response.data)

    # Change
    response = unauthenticated_api_client.patch(url, data={'name': 'new name'})
    assert response.status_code == expected_change_status, (response.status_code, response.data)

    # Delete
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == expected_delete_status, (response.status_code, response.data)


@pytest.mark.parametrize(
    'user_case, has_access',
    [
        ('superuser', True),
        pytest.param('admin_of_app_org', True, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        ('user_in_org', False),
        ('user', False),
        ('anon', False),
    ],
)
@pytest.mark.django_db
def test_oauth2_application_create(
    request, user_case, has_access, org_member_rd, org_admin_rd, random_user, oauth2_application, organization, unauthenticated_api_client
):
    """
    From awx.main.access.OAuth2ApplicationAccess:

    I can create OAuth 2 applications when:
     - I am a superuser.
     - I am the admin of the organization of the application.
    """
    app = oauth2_application[0]
    app.organization = organization
    app.user = random_user
    app.save()

    expected_create_status = 201 if has_access else 403

    # Determine the user based on the test case (adding them to organizations, etc. as necessary).
    if user_case == 'superuser':
        # - I am a superuser.
        user = request.getfixturevalue('admin_user')  # Nothing to do, just use the admin user
    else:
        user = request.getfixturevalue('random_user_1')
        if user_case == 'admin_of_app_org':
            # - I am the admin of the organization of the application.
            RoleDefinition.objects.managed.org_admin.give_permission(user, organization)  # And make me an admin of the org
        elif user_case == 'user_in_org':
            # - I am a user in the organization of the application.
            RoleDefinition.objects.managed.org_member.give_permission(user, organization)  # Add me to the org
        elif user_case == 'user':
            # Negative case, do nothing, the user is just some random user
            pass
        elif user_case == 'anon':
            user = None
            expected_create_status = 401
        else:
            raise ValueError(f"Invalid user_case: {user_case}")

    if user is not None:
        unauthenticated_api_client.force_login(user)
    url = reverse("application-list")
    data = {
        'name': 'new app',
        'organization': organization.id,
        'client_type': 'confidential',
        'authorization_grant_type': 'password',
    }
    if user is not None:
        data['user'] = user.id
    response = unauthenticated_api_client.post(url, data=data)
    assert response.status_code == expected_create_status, (response.status_code, response.data)


@pytest.mark.parametrize(
    'user_case, has_access',
    [
        ('superuser', True),
        ('admin_of_token_app_org', True),
        ('user_of_token', True),
        ('user_in_app_org', False),
        ('user', False),
        ('anon', False),
    ],
)
@pytest.mark.django_db
def test_oauth2_application_token_read_change_delete(
    request,
    user_case,
    has_access,
    org_member_rd,
    org_admin_rd,
    random_user,
    oauth2_application,
    oauth2_user_application_token,
    organization,
    unauthenticated_api_client,
):
    """
    From awx.main.access.OAuth2TokenAccess:

    I can read, change or delete an app token when:
     - I am a superuser.
     - I am the admin of the organization of the application of the token.
     - I am the user of the token.
    """
    app = oauth2_application[0]
    app.organization = organization
    app.user = random_user
    app.save()

    expected_read_status = 200 if has_access else 403
    expected_change_status = 200 if has_access else 403
    expected_delete_status = 204 if has_access else 403

    # Determine the user based on the test case (adding them to organizations, etc. as necessary).
    if user_case == 'superuser':
        # - I am a superuser.
        user = request.getfixturevalue('admin_user')  # Nothing to do, just use the admin user
    else:
        user = request.getfixturevalue('random_user_1')
        if user_case == 'admin_of_token_app_org':
            # - I am the admin of the organization of the application of the token.
            RoleDefinition.objects.managed.org_admin.give_permission(user, organization)  # Make me an admin of the org
        elif user_case == 'user_of_token':
            # - I am the user of the token.
            user = oauth2_user_application_token.user
        elif user_case == 'user_in_app_org':
            # Negative case, user is in the org but not an admin or the token user
            RoleDefinition.objects.managed.org_member.give_permission(user, organization)  # Add me to the org
        elif user_case == 'user':
            # Negative case, do nothing, the user is just some random user
            pass
        elif user_case == 'anon':
            user = None
            expected_read_status = 401
            expected_change_status = 401
            expected_delete_status = 401
        else:
            raise ValueError(f"Invalid user_case: {user_case}")

    if user is not None:
        unauthenticated_api_client.force_login(user)
    url = reverse("token-detail", args=[oauth2_user_application_token.id])

    # Read
    response = unauthenticated_api_client.get(url)
    assert response.status_code == expected_read_status, (response.status_code, response.data)

    # Change
    response = unauthenticated_api_client.patch(url, data={'description': 'new description'})
    assert response.status_code == expected_change_status, (response.status_code, response.data)

    # Delete
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == expected_delete_status, (response.status_code, response.data)


@pytest.mark.parametrize(
    'user_case, has_access',
    [
        ('superuser', True),
        pytest.param('admin_of_app_user_org', True, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        pytest.param('user_in_app_org', True, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        ('user', False),
        ('anon', False),
    ],
)
@pytest.mark.django_db
def test_oauth2_application_token_create(
    request, user_case, has_access, org_member_rd, org_admin_rd, random_user, oauth2_application, organization, unauthenticated_api_client
):
    """
    From awx.main.access.OAuth2TokenAccess:

    I can create an OAuth2 app token when:
     - I have the read permission of the related application.

    ---

    Inheriting from app access:
    I can read OAuth 2 applications when:
     - I am a superuser.
     - I am the admin of the organization of the user of the application.
     - I am a user in the organization of the application.
    """
    app = oauth2_application[0]
    app.organization = organization
    app.user = random_user
    app.save()

    expected_create_status = 201 if has_access else 403

    if user_case == 'superuser':
        # - I am a superuser.
        user = request.getfixturevalue('admin_user')  # Nothing to do, just use the admin user
    else:
        user = request.getfixturevalue('random_user_1')
        second_org = request.getfixturevalue('organization_1')
        if user_case == 'admin_of_app_user_org':
            # - I am the admin of the organization of the user of the application.
            RoleDefinition.objects.managed.org_member.give_permission(user, second_org)  # Add me to the org
            RoleDefinition.objects.managed.org_admin.give_permission(user, second_org)  # And make me an admin of the org
            RoleDefinition.objects.managed.org_member.give_permission(app.user, second_org)  # Add the app owner user to the org
        elif user_case == 'user_in_app_org':
            # - I am a user in the organization of the application.
            RoleDefinition.objects.managed.org_member.give_permission(user, organization)  # Add me to the org
        elif user_case == 'user':
            # Negative case, do nothing, the user is just some random user
            pass
        elif user_case == 'anon':
            user = None
            expected_create_status = 401
        else:
            raise ValueError(f"Invalid user_case: {user_case}")

    if user is not None:
        unauthenticated_api_client.force_login(user)
    url = reverse("token-list")

    # Create
    data = {
        'application': app.id,
        'description': 'new token',
        'scope': 'read write',
    }
    response = unauthenticated_api_client.post(url, data=data)
    assert response.status_code == expected_create_status, (response.status_code, response.data)


@pytest.mark.django_db
def test_oauth2_pat_create(request, org_member_rd, org_admin_rd, user, random_user, user_api_client):
    """
    From awx.main.access.OAuth2TokenAccess:

    I can create an OAuth2 Personal Access Token when:
     - I am a user.  But I can only create a PAT for myself.
    """

    url = reverse("token-list")

    # Create PAT
    data = {
        'description': 'new PAT',
        'scope': 'read write',
    }
    response = user_api_client.post(url, data=data)
    assert response.status_code == 201
    token_id = response.data['id']
    token = OAuth2AccessToken.objects.get(id=token_id)
    assert token.user == user

    # Create PAT with another user
    data = {
        'description': 'new PAT that is not mine',
        'scope': 'read write',
        'user': random_user.id,
    }
    response = user_api_client.post(url, data=data)
    # We don't block the request but we force the user to be the requester
    assert response.status_code == 201
    token_id = response.data['id']
    token = OAuth2AccessToken.objects.get(id=token_id)
    assert token.user == user  # not random_user


@pytest.mark.parametrize(
    'user_case, has_access',
    [
        ('superuser', True),
        ('user_of_token', True),
        ('user', False),
        ('anon', False),
    ],
)
@pytest.mark.django_db
def test_oauth2_pat_read_change_delete(request, user_case, has_access, org_member_rd, org_admin_rd, unauthenticated_api_client, oauth2_user_pat):
    """
    From awx.main.access.OAuth2TokenAccess:

    I can read, change or delete a personal token when:
     - I am the user of the token
     - I am the superuser
    """
    expected_read_status = 200 if has_access else 403
    expected_change_status = 200 if has_access else 403
    expected_delete_status = 204 if has_access else 403

    # Determine the user based on the test case (adding them to organizations, etc. as necessary).
    if user_case == 'superuser':
        # - I am the superuser
        user = request.getfixturevalue('admin_user')  # Nothing to do, just use the admin user
    elif user_case == 'user_of_token':
        # - I am the user of the token
        user = oauth2_user_pat.user
    elif user_case == 'user':
        # Negative case, the user is just some random user
        user = request.getfixturevalue('random_user')
    elif user_case == 'anon':
        user = None
        expected_read_status = 401
        expected_change_status = 401
        expected_delete_status = 401
    else:
        raise ValueError(f"Invalid user_case: {user_case}")

    if user is not None:
        unauthenticated_api_client.force_login(user)
    url = reverse("token-detail", args=[oauth2_user_pat.id])

    # Read
    response = unauthenticated_api_client.get(url)
    assert response.status_code == expected_read_status, (response.status_code, response.data)

    # Change
    response = unauthenticated_api_client.patch(url, data={'description': 'new description'})
    assert response.status_code == expected_change_status, (response.status_code, response.data)

    # Delete
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == expected_delete_status, (response.status_code, response.data)
