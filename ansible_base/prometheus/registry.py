"""
Idempotent helpers for registering prometheus_client metrics.

Metrics registered via these functions are stored in a module-level dict so that
re-registration (e.g. on module reload in tests) returns the existing instance
instead of raising ValueError from prometheus_client's global REGISTRY.

Pass ``registry`` explicitly to opt out of this caching and register into an
isolated CollectorRegistry — useful for test isolation.
"""
from typing import Sequence

from prometheus_client import REGISTRY as _GLOBAL_REGISTRY
from prometheus_client import Counter, Gauge, Histogram, Summary

_registry: dict[str, object] = {}


def _get_or_create(cls, name: str, documentation: str, labels: Sequence[str], registry=None, **kwargs):
    if registry is not None:
        return cls(name, documentation, labelnames=list(labels), registry=registry, **kwargs)
    if name not in _registry:
        _registry[name] = cls(name, documentation, labelnames=list(labels), **kwargs)
    return _registry[name]


def counter(name: str, documentation: str, labels: Sequence[str] = (), *, registry=None) -> Counter:
    """Get or create a Counter metric."""
    return _get_or_create(Counter, name, documentation, labels, registry=registry)


def gauge(name: str, documentation: str, labels: Sequence[str] = (), *, registry=None) -> Gauge:
    """Get or create a Gauge metric."""
    return _get_or_create(Gauge, name, documentation, labels, registry=registry)


def histogram(
    name: str,
    documentation: str,
    labels: Sequence[str] = (),
    *,
    buckets: Sequence[float] = Histogram.DEFAULT_BUCKETS,
    registry=None,
) -> Histogram:
    """Get or create a Histogram metric."""
    return _get_or_create(Histogram, name, documentation, labels, registry=registry, buckets=buckets)


def summary(name: str, documentation: str, labels: Sequence[str] = (), *, registry=None) -> Summary:
    """Get or create a Summary metric."""
    return _get_or_create(Summary, name, documentation, labels, registry=registry)
