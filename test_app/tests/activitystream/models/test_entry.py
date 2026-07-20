import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import models as db_models

from ansible_base.activitystream.apps import get_activity_stream_entries
from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.utils.response import get_relative_url


def test_activitystream_entry_immutable(system_user, animal):
    """
    Trying to modify an Entry object should raise an exception.
    """
    entry = get_activity_stream_entries(animal).first()
    entry.operation = "delete"
    with pytest.raises(ValueError) as excinfo:
        entry.save()

    assert "Entry is immutable" in str(excinfo.value)


def test_activitystream_registered_model_related(admin_api_client, user, organization):
    url = get_relative_url('user-detail', kwargs={'pk': user.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'activity_stream' in response.data['related']
    activity_stream_url = response.data['related']['activity_stream']
    content_type = ContentType.objects.get_for_model(user)
    assert f'object_id={user.pk}' in activity_stream_url
    assert f'content_type={content_type.pk}' in activity_stream_url

    # organization isn't in ACTIVITY_STREAM_MODELS, so it shouldn't show AS in related
    url = get_relative_url('organization-detail', kwargs={'pk': organization.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'activity_stream' not in response.data['related']


def test_auditable_model_has_no_db_fields():
    """
    AuditableModel must remain a pure mixin with no database fields.
    Models conditionally inherit from AuditableModel based on whether
    activitystream is installed (e.g., AAPFlag). Adding a DB field would
    create environment-dependent migrations.
    """
    db_fields = [f.name for f in AuditableModel._meta.local_fields if isinstance(f, db_models.Field)]
    assert db_fields == [], (
        f"AuditableModel must not have DB fields (found: {db_fields}). "
        "This would break models that conditionally inherit from it "
        "based on whether activitystream is in INSTALLED_APPS."
    )
