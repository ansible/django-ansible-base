import pytest

from ansible_base.activitystream.models import Entry

def test_activitystream_entry_immutable(system_user, animal):
    """
    Trying to modify an Entry object should raise an exception.
    """
    entry = animal.activity_stream_entries.first()
    entry.operation = "delete"
    with pytest.raises(RuntimeError) as excinfo:
        entry.save()

    assert "Activity stream entries are immutable" in str(excinfo.value)
