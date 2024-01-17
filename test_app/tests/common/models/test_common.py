import pytest

from test_app.models import EncryptionModel


@pytest.mark.django_db
def test_save_encryption():
    model = EncryptionModel.objects.create(testing1='c')
    model.save()

    saved_model = EncryptionModel.objects.first()
    assert saved_model.testing2 == 'b'
    assert saved_model.testing1 == 'c'


@pytest.mark.django_db
def test_name_in_summary_fields():
    model = EncryptionModel.objects.create()
    assert 'name' in model.summary_fields()
