import pytest
from django.test.utils import override_settings
from rest_framework.reverse import reverse


@pytest.mark.django_db
def test_patch_system_role(admin_api_client, global_inv_rd):
    "Making a PATCH to a system role should not re-validate the content_type"
    url = reverse('roledefinition-detail', kwargs={'pk': global_inv_rd.pk})
    response = admin_api_client.patch(url, data={'name': 'my new name'})
    assert response.status_code == 200
    global_inv_rd.refresh_from_db()
    assert global_inv_rd.name == 'my new name'
    assert global_inv_rd.content_type is None
    assert response.data['content_type'] == None


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API=False)
def test_patch_object_role(admin_api_client, inv_rd):
    "Making a PATCH to a system role should not re-validate the content_type"
    url = reverse('roledefinition-detail', kwargs={'pk': inv_rd.pk})
    response = admin_api_client.patch(url, data={'name': 'my new name'})
    assert response.status_code == 200
    inv_rd.refresh_from_db()
    assert inv_rd.name == 'my new name'
    assert inv_rd.content_type.model == 'inventory'
    assert response.data['content_type'] == 'aap.inventory'
