import pytest
from django.test.utils import override_settings

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, DABPermission
from ansible_base.rbac.remote import get_local_resource_prefix


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_ROLES_REQUIRE_VIEW=True)
def test_create_remote_role_missing_view_returns_400_with_clear_message(admin_api_client):
    """Reproduces AAP-50803: remote stand-in cls lacks verbose_name, causing 500.

    Ensure creating a role for a remote content type with change-only permission
    returns HTTP 400 and a readable message that mentions view permission is required.
    """
    # Ensure a remote content type exists (service not shared/local)
    local_service = get_local_resource_prefix()
    remote_ct = DABContentType.objects.exclude(service__in=("shared", local_service)).first()
    if remote_ct is None:
        # Create a representative remote content type (e.g., awx.inventory)
        remote_ct, _ = DABContentType.objects.get_or_create(
            service="awx",
            app_label="awx",
            model="inventory",
            defaults={"pk_field_type": "integer"},
        )

    # Ensure both view and change permissions exist so the validator enforces the view requirement
    view_perm, _ = DABPermission.objects.get_or_create(
        content_type=remote_ct,
        codename="view_inventory",
        defaults={"name": "Can view inventory"},
    )
    change_perm, _ = DABPermission.objects.get_or_create(
        content_type=remote_ct,
        codename="change_inventory",
        defaults={"name": "Can change inventory"},
    )

    url = get_relative_url('roledefinition-list')
    response = admin_api_client.post(
        url,
        data={
            'name': 'remote-change-no-view',
            'description': '',
            'content_type': remote_ct.api_slug,
            'permissions': [change_perm.api_slug],
        },
    )

    # Expected: 400 with message indicating view is required
    assert response.status_code == 400, response.data
    msg = str(response.data).lower()
    assert 'view' in msg and ('needs to include view' in msg or 'required' in msg)
