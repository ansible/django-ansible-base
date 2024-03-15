import pytest

from ansible_base.lib.abstract_models import CommonModel, ImmutableModel
from test_app.models import ImmutableLogEntry, ImmutableLogEntryNotCommon


@pytest.mark.django_db
@pytest.mark.parametrize('model', [ImmutableLogEntry, ImmutableLogEntryNotCommon])
def test_immutable_model_is_immutable(model):
    """
    ImmutableModel prevents saves from happening after the first save.
    """
    log_entry = model(message="Oh no! An important message!")
    log_entry.save()  # We can save it once
    log_entry.message = "Oh no! An even more important message!"

    with pytest.raises(ValueError) as excinfo:
        log_entry.save()
    assert excinfo.value.args[0] == f"{model.__name__} is immutable and cannot be modified."

    # Ensure that nothing got updated before the exception was raised
    log_entry.refresh_from_db()
    assert log_entry.message == "Oh no! An important message!"


def test_immutable_model_mixin_must_be_first():
    """
    We raise an error if the ImmutableModel mixin is used improperly and doesn't come first.
    """
    with pytest.raises(ValueError) as excinfo:

        class FooModel(CommonModel, ImmutableModel):
            pass

    assert excinfo.value.args[0] == "ImmutableModel must be the first base class for FooModel"


@pytest.mark.django_db
def test_immutable_model_modified_fields_gone_after_save():
    """
    After save(), ImmutableModels have no modified_on/modified_by fields.
    """
    instance = ImmutableLogEntry(message="Oh no! An important message!")

    instance.save()

    with pytest.raises(AttributeError):
        instance.modified

    with pytest.raises(AttributeError):
        instance.modified_by
