import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.test import TestCase
from django.test.utils import isolate_apps

from ansible_base.rbac.models import DABContentType
from ansible_base.rbac.remote import RemoteObject
from test_app.models import Inventory, Organization


@pytest.mark.django_db
def test_migration_shadows_real_contenttype():
    assert DABContentType.objects.count() > 0  # sanity
    for dab_ct in DABContentType.objects.all():
        ct = ContentType.objects.get_by_natural_key(dab_ct.app_label, dab_ct.model)
        assert ct.id == dab_ct.id


@pytest.mark.django_db
def test_auto_create_content_type():
    DABContentType.objects.get_for_model(Inventory)
    DABContentType.objects.get_for_model(Organization)
    DABContentType.objects.all().delete()
    inv_ct = DABContentType.objects.get_for_model(Inventory)
    assert inv_ct.model == 'inventory'
    assert inv_ct.service == 'aap'

    org_ct = DABContentType.objects.get_for_model(Organization)
    assert org_ct.service == 'shared'


@pytest.mark.django_db
def test_auto_create_content_type_multiples():
    DABContentType.objects.get_for_model(Inventory)
    DABContentType.objects.get_for_model(Organization)
    DABContentType.objects.all().delete()
    data = DABContentType.objects.get_for_models(Inventory, Organization)
    inv_ct = data[Inventory]
    org_ct = data[Organization]

    assert inv_ct.model == 'inventory'
    assert inv_ct.service == 'aap'
    assert org_ct.service == 'shared'


@pytest.mark.django_db
def test_post_migrate_creates_contenttype():
    ct = DABContentType.objects.get(app_label="test_app", model="inventory")
    assert ct.service == "aap"


@pytest.mark.django_db
def test_shared_types_created_post_migrate():
    ct = DABContentType.objects.get(app_label="test_app", model='organization')
    assert ct.service == 'shared'
    assert ct.model_class() is Organization


@pytest.mark.django_db
class DABContentTypeTests(TestCase):
    """These tests originally came from Django contenttypes"""

    def setUp(self):
        DABContentType.objects.clear_cache()
        self.addCleanup(DABContentType.objects.clear_cache)

    def test_lookup_cache(self):
        with self.assertNumQueries(1):
            DABContentType.objects.get_for_model(Inventory)
        with self.assertNumQueries(0):
            ct = DABContentType.objects.get_for_model(Inventory)
        with self.assertNumQueries(0):
            DABContentType.objects.get_for_id(ct.id)
        with self.assertNumQueries(0):
            DABContentType.objects.get_by_natural_key(
                ct.service,
                ct.app_label,
                ct.model,
            )
        DABContentType.objects.clear_cache()
        with self.assertNumQueries(1):
            DABContentType.objects.get_for_model(Inventory)

    @isolate_apps("tests")
    def test_get_for_model_not_registered(self):
        class ModelCreatedOnTheFly(models.Model):
            name = models.CharField(max_length=10)

            class Meta:
                app_label = "tests"

        with pytest.raises(RuntimeError):
            DABContentType.objects.get_for_model(ModelCreatedOnTheFly)


@pytest.mark.django_db
def test_get_object_for_this_type_remote():
    """Remote objects should return a remote proxy."""
    ct = DABContentType.objects.create(
        service="remote_proj",
        app_label="testapp",
        model="book",
    )

    obj = ct.get_object_for_this_type(pk=1)

    assert isinstance(obj, RemoteObject)
    assert obj.object_id == 1
    assert obj.content_type == ct


@pytest.mark.django_db
def test_get_all_objects_for_this_type_remote():
    ct = DABContentType.objects.create(
        service="remote_proj2",
        app_label="testapp",
        model="book",
    )

    objs = ct.get_all_objects_for_this_type(pk__in=[1, 2])

    assert [o.object_id for o in objs] == [1, 2]
    assert all(isinstance(o, RemoteObject) for o in objs)
