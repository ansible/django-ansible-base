
import pytest
from metrics_app.models import Metrics

@pytest.mark.django_db
def test_create_metric_default_payload():
  result = Metrics.objects.create()
  result.save()
  assert result.payload == dict()

@pytest.mark.django_db
def test_modifying_metric_updates_modified_time():
  # TODO: Implement this test
  result = Metrics.objects.create()
  result.payload = {"name":"Alex"}
  og_modified = result.modified
  new_result = result.save()
  assert og_modified != result.modified
  # raise NotImplementedError()
