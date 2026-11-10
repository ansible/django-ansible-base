import pytest
from prometheus_client import CollectorRegistry

from ansible_base.prometheus.registry import counter, gauge, histogram, summary


def test_counter_returns_same_instance():
    a = counter('test_counter_idempotent_total', 'test')
    b = counter('test_counter_idempotent_total', 'test')
    assert a is b


def test_gauge_returns_same_instance():
    a = gauge('test_gauge_idempotent', 'test')
    b = gauge('test_gauge_idempotent', 'test')
    assert a is b


def test_histogram_returns_same_instance():
    a = histogram('test_histogram_idempotent_seconds', 'test')
    b = histogram('test_histogram_idempotent_seconds', 'test')
    assert a is b


def test_summary_returns_same_instance():
    a = summary('test_summary_idempotent_seconds', 'test')
    b = summary('test_summary_idempotent_seconds', 'test')
    assert a is b


def test_isolated_registry_not_cached_in_module(prometheus_registry):
    from ansible_base.prometheus import registry as reg

    name = 'test_isolated_not_in_module_cache_total'
    counter(name, 'test', registry=prometheus_registry)
    # Metrics created with a custom registry must not pollute the module-level cache.
    assert name not in reg._registry


def test_counter_with_labels_increments(prometheus_registry):
    c = counter('test_labelled_counter_total', 'labelled', labels=['env'], registry=prometheus_registry)
    c.labels(env='test').inc()
    assert c.labels(env='test')._value.get() == 1.0


def test_gauge_set(prometheus_registry):
    g = gauge('test_gauge_set', 'set test', registry=prometheus_registry)
    g.set(42)
    assert g._value.get() == 42.0


def test_histogram_observe(prometheus_registry):
    h = histogram('test_histogram_observe_seconds', 'observe test', registry=prometheus_registry)
    h.observe(0.5)
    assert h._sum.get() == 0.5


def test_custom_histogram_buckets(prometheus_registry):
    h = histogram('test_custom_buckets_seconds', 'custom buckets', buckets=[0.1, 0.5, 1.0], registry=prometheus_registry)
    assert list(h._upper_bounds) == [0.1, 0.5, 1.0, float('inf')]
