"""
Dummy models for optional django-ansible-base apps.

These provide no-op implementations when optional apps are not installed,
preventing import crashes while maintaining interface compatibility.
"""

from django.db import models


class DummyAuditableModel(models.Model):
    """
    Dummy AuditableModel for services without activitystream app.

    Provides the same interface as the real AuditableModel but with no
    activity logging functionality. This prevents import crashes in services
    like AWX/EDA that don't include 'ansible_base.activitystream' in INSTALLED_APPS.
    """

    activity_stream_excluded_field_names = []
    activity_stream_limit_field_names = []

    @property
    def activity_stream_entries(self):
        """Return empty queryset for dummy model."""

        # Can't import Entry directly - would crash AWX/EDA
        # Return a minimal QuerySet-like object that supports count() and last()
        class EmptyActivityStream:
            def count(self):
                return 0

            def last(self):
                return None

            def all(self):
                return self

            def order_by(self, *args):
                return self

            def __iter__(self):
                return iter([])

        return EmptyActivityStream()

    def extra_related_fields(self, request):
        """Return empty dict for dummy model."""
        return {}

    class Meta:
        abstract = True
