from prometheus_client import CONTENT_TYPE_LATEST


def test_metrics_endpoint_returns_200(client):
    response = client.get('/metrics/')
    assert response.status_code == 200


def test_metrics_endpoint_content_type(client):
    response = client.get('/metrics/')
    assert response['Content-Type'] == CONTENT_TYPE_LATEST


def test_metrics_endpoint_contains_default_metrics(client):
    client.get('/metrics/')  # generate at least one data point
    response = client.get('/metrics/')
    content = response.content.decode()
    assert 'django_http_requests_total' in content
    assert 'django_http_request_duration_seconds' in content


def test_metrics_endpoint_contains_process_metrics(client):
    response = client.get('/metrics/')
    content = response.content.decode()
    # prometheus_client registers process/platform collectors by default
    assert 'python_info' in content


def test_metrics_endpoint_multiprocess_skipped_without_dir(client, monkeypatch):
    monkeypatch.delenv('PROMETHEUS_MULTIPROC_DIR', raising=False)
    monkeypatch.delenv('prometheus_multiproc_dir', raising=False)
    response = client.get('/metrics/')
    assert response.status_code == 200
