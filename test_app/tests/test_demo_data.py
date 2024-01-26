import pytest

from test_app.management.commands.create_demo_data import Command
from test_app.models import Organization


@pytest.mark.django_db
def test_demo_data_no_op():
    Organization.objects.create(name='stub')
    Command().handle()
    assert Organization.objects.count() == 1


@pytest.mark.django_db
def test_demo_data_create_data():
    Command().handle()
    assert Organization.objects.filter(name='AWX_community').exists()
