import logging
import os
from unittest.mock import patch

import pytest

from ansible_base.prometheus.instrument import setup_prometheus


def test_setup_warns_when_middleware_missing(settings, caplog):
    middleware_without_prometheus = [m for m in settings.MIDDLEWARE if 'PrometheusMiddleware' not in m]
    settings.MIDDLEWARE = middleware_without_prometheus
    with caplog.at_level(logging.WARNING, logger='ansible_base.prometheus.instrument'):
        setup_prometheus()
    assert any('PrometheusMiddleware' in r.message for r in caplog.records)


def test_setup_no_warning_when_middleware_present(settings, caplog):
    assert 'ansible_base.prometheus.middleware.PrometheusMiddleware' in settings.MIDDLEWARE
    with caplog.at_level(logging.WARNING, logger='ansible_base.prometheus.instrument'):
        setup_prometheus()
    assert not any('PrometheusMiddleware' in r.message for r in caplog.records)


def test_setup_sets_multiproc_env_from_settings(settings, monkeypatch, tmp_path):
    monkeypatch.delenv('PROMETHEUS_MULTIPROC_DIR', raising=False)
    settings.ANSIBLE_PROMETHEUS_MULTIPROC_DIR = str(tmp_path)
    setup_prometheus()
    # env var is set; clean_prometheus_multiproc_env fixture removes it after the test
    assert os.environ.get('PROMETHEUS_MULTIPROC_DIR') == str(tmp_path)


def test_setup_does_not_override_existing_multiproc_env(settings, monkeypatch, tmp_path):
    monkeypatch.setenv('PROMETHEUS_MULTIPROC_DIR', str(tmp_path))
    settings.ANSIBLE_PROMETHEUS_MULTIPROC_DIR = '/new/path'
    setup_prometheus()
    assert os.environ['PROMETHEUS_MULTIPROC_DIR'] == str(tmp_path)
