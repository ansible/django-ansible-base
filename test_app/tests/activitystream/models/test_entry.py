import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.lib.utils.response import get_relative_url


def test_activitystream_entry_immutable(system_user, animal):
    """
    Trying to modify an Entry object should raise an exception.
    """
    entry = animal.activity_stream_entries.first()
    entry.operation = "delete"
    with pytest.raises(ValueError) as excinfo:
        entry.save()

    assert "Entry is immutable" in str(excinfo.value)


def test_activitystream_auditablemodel_related(admin_api_client, user, organization):
    url = get_relative_url('user-detail', kwargs={'pk': user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'activity_stream' in response.data['related']
    activity_stream_url = response.data['related']['activity_stream']
    content_type = ContentType.objects.get_for_model(user)
    assert f'object_id={user.pk}' in activity_stream_url
    assert f'content_type={content_type.pk}' in activity_stream_url

    # organization isn't an AuditableModel, so it shouldn't show AS in related
    url = get_relative_url('organization-detail', kwargs={'pk': organization.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'activity_stream' not in response.data['related']
