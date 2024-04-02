import pytest


def test_activitystream_entry_immutable(system_user, animal):
    """
    Trying to modify an Entry object should raise an exception.
    """
    entry = animal.activity_stream_entries.first()
    entry.operation = "delete"
    with pytest.raises(ValueError) as excinfo:
        entry.save()

    assert "Entry is immutable" in str(excinfo.value)
