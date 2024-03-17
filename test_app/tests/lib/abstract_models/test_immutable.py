import pytest

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


@pytest.mark.django_db
def test_immutable_model_has_no_modified_fields():
    """
    After ImmutableCommonModel should never have a modified/modified_by field.
    """
    instance = ImmutableLogEntry(message="Oh no! An important message!")

    instance.save()

    with pytest.raises(AttributeError):
        instance.modified

    with pytest.raises(AttributeError):
        instance.modified_by
