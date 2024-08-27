import pytest

from ansible_base.lib.utils.db import migrations_are_complete


@pytest.mark.django_db
def test_migrations_are_complete():
    "If you are running tests, migrations (test database) should be complete"
    assert migrations_are_complete()
