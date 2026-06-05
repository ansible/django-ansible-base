import os

import pytest
from prometheus_client import CollectorRegistry


@pytest.fixture
def prometheus_registry():
    """An isolated CollectorRegistry for test-scoped metrics."""
    return CollectorRegistry()


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_superuser(username='prometheus_admin', password='pass', email='prometheus_admin@example.com')


@pytest.fixture(autouse=True)
def clean_prometheus_multiproc_env():
    """Ensure PROMETHEUS_MULTIPROC_DIR is never leaked between tests.

    setup_prometheus() sets the env var via os.environ.setdefault() which
    monkeypatch does not track automatically — this fixture cleans it up.
    """
    yield
    os.environ.pop('PROMETHEUS_MULTIPROC_DIR', None)
    os.environ.pop('prometheus_multiproc_dir', None)
