import pytest
from metrics_app.models import Metric

@pytest.mark.django_db
def test_create_metric_default_payload():
  result = Metric.objects.create()
  result.save()
  assert result.payload == dict()

@pytest.mark.django_db
def test_modifying_metric_updates_modified_time():
  # TODO: Implement this test
  raise NotImplementedError()