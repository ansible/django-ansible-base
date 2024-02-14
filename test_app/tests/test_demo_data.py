import pytest

from test_app.management.commands.create_demo_data import Command
from test_app.models import Organization


@pytest.mark.django_db
def test_demo_data_with_existing_data():
    Organization.objects.create(name='stub')
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').exists()
    assert Organization.objects.filter(name='stub').exists()


@pytest.mark.django_db
def test_demo_data_create_data():
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').exists()


@pytest.mark.django_db
def test_demo_data_idempotent():
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').exists()
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').count() == 1
