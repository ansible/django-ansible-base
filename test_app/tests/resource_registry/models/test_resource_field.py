import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.resource_registry.models import Resource
from test_app.models import Organization


@pytest.mark.django_db
def test_resource_field_select_related(organization, organization_1, organization_2):
    org_ctype = ContentType.objects.get_for_model(Organization)

    org_qs = Organization.objects.select_related("resource").all()
    resource_qs = Resource.objects.filter(content_type=org_ctype)

    assert len(org_qs) > 1
    assert len(org_qs) == len(resource_qs)

    org_names = set([org.name for org in org_qs])
    org_resource_names = set([org.resource.name for org in org_qs])
    org_pks = set([str(org.pk) for org in org_qs])
    org_ansible_ids = set([org.resource.ansible_id for org in org_qs])

    resource_names = set([resource.name for resource in resource_qs])
    resource_object_ids = set([resource.object_id for resource in resource_qs])
    resource_ansible_ids = set([resource.ansible_id for resource in resource_qs])

    assert org_names == resource_names
    assert org_names == org_resource_names
    assert org_pks == resource_object_ids
    assert org_ansible_ids == resource_ansible_ids

    for org in org_qs:
        assert org.resource.pk == Resource.objects.get(object_id=org.pk, content_type=org_ctype).pk


@pytest.mark.django_db
def test_resource_field_prefetch_related(organization, organization_1, organization_2):
    org_ctype = ContentType.objects.get_for_model(Organization)

    assert "dab_resource_registry_resource" not in str(Organization.objects.prefetch_related("resource").all().query)

    org_qs = list(Organization.objects.prefetch_related("resource").all())
    resource_qs = Resource.objects.filter(content_type=org_ctype)

    assert len(org_qs) > 1
    assert len(org_qs) == len(resource_qs)

    org_names = set([org.name for org in org_qs])
    org_resource_names = set([org.resource.name for org in org_qs])
    org_pks = set([str(org.pk) for org in org_qs])
    org_ansible_ids = set([org.resource.ansible_id for org in org_qs])

    resource_names = set([resource.name for resource in resource_qs])
    resource_object_ids = set([resource.object_id for resource in resource_qs])
    resource_ansible_ids = set([resource.ansible_id for resource in resource_qs])

    assert org_names == resource_names
    assert org_names == org_resource_names
    assert org_pks == resource_object_ids
    assert org_ansible_ids == resource_ansible_ids

    for org in org_qs:
        assert org.resource.pk == Resource.objects.get(object_id=org.pk, content_type=org_ctype).pk


@pytest.mark.django_db
def test_resource_field_get(organization):
    """
    Test that <resource_model>.resource returns the correct Resource object.
    """
    resource = Resource.objects.get(object_id=organization.pk, content_type=ContentType.objects.get_for_model(organization))

    assert organization.resource.ansible_id == resource.ansible_id
    assert organization.name == organization.resource.name
    assert str(organization.pk) == resource.object_id
    assert organization.resource.pk == resource.pk


@pytest.mark.django_db
def test_resource_field_filtering(organization):
    """
    Test that queryset filter works.
    """
    resource = Resource.objects.get(object_id=organization.pk, content_type=ContentType.objects.get_for_model(organization))

    org = Organization.objects.get(resource__ansible_id=resource.resource_id)
    assert org.resource.pk == resource.pk

    org = Organization.objects.get(resource__name=organization.name)
    assert org.resource.pk == resource.pk
