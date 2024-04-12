import pytest

from django.urls import reverse

from test_app.models import User


@pytest.mark.django_db
def test_org_admin_can_edit_user(user, user_api_client, organization, org_member_rd, org_admin_rd):
    rando = User.objects.create(username='rando')
    url = reverse('user-detail', kwargs={'pk': rando.pk})
    org_member_rd.give_permission(rando, organization)
    org_member_rd.give_permission(user, organization)

    # Unrelated users can not edit user
    response = user_api_client.patch(url, data={'email': 'foo@foo.invalid'})
    assert response.status_code == 403

    # Organization admins can edit users
    response = user_api_client.patch(url, data={'email': 'foo@foo.invalid'})
    assert response.status_code == 200
