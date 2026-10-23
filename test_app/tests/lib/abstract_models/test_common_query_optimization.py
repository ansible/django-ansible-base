import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.lib.abstract_models.common import get_url_for_object
from test_app.models import Organization, Team, User


@pytest.mark.django_db
class TestRelatedFieldsQueryOptimization:
    """Verify that related_fields() builds correct URLs using raw FK IDs
    without loading related objects from the database."""

    def test_related_fields_urls_match_original_method(self, system_user):
        """The optimized related_fields() must produce the same URLs as
        loading the full FK object and calling get_url_for_object()."""
        org = Organization.objects.create(name="test-org")
        team = Team.objects.create(name="test-team", organization=org)

        related = team.related_fields(None)

        # The organization FK should produce a valid URL
        assert "organization" in related
        expected_url = get_url_for_object(org)
        assert related["organization"] == expected_url

    def test_related_fields_skips_null_fks(self, system_user):
        """Null FK fields should not appear in related_fields output."""
        org = Organization.objects.create(name="test-org")
        # Force a known-null FK to make the assertion non-vacuous
        Organization.objects.filter(pk=org.pk).update(modified_by=None)
        org.refresh_from_db()
        assert org.modified_by_id is None

        related = org.related_fields(None)

        assert "modified_by" not in related

    def test_related_fields_no_lazy_load_queries(self, system_user):
        """related_fields() should build URLs from raw FK IDs without loading
        related objects, even when the object was fetched without select_related."""
        org = Organization.objects.create(name="test-org")
        team = Team.objects.create(name="test-team", organization=org)

        # Re-fetch without select_related so this exercises the raw FK-id path.
        # With select_related, the old implementation would also be query-free.
        team = Team.objects.get(pk=team.pk)

        with CaptureQueriesContext(connection) as ctx:
            team.related_fields(None)

        # With the optimization, related_fields uses raw FK IDs for URL
        # construction and should not trigger any FK lazy-load queries.
        assert len(ctx.captured_queries) == 0, f"related_fields() triggered {len(ctx.captured_queries)} queries: " f"{[q['sql'] for q in ctx.captured_queries]}"


@pytest.mark.django_db
class TestGetSummaryFieldsOptimization:
    """Verify that get_summary_fields() skips null FKs without loading them."""

    def test_summary_fields_null_fk_no_query(self, system_user):
        """get_summary_fields() should not trigger any query for a null FK
        even without select_related."""
        org = Organization.objects.create(name="test-org")
        # Force null FKs to exercise the null-FK short-circuit path
        Organization.objects.filter(pk=org.pk).update(modified_by=None, created_by=None)
        # Pre-load resource (non-null) so only null-FK behavior is tested
        org = Organization.objects.select_related("resource").get(pk=org.pk)
        assert org.modified_by_id is None
        assert org.created_by_id is None

        with CaptureQueriesContext(connection) as ctx:
            summary = org.get_summary_fields()

        assert isinstance(summary, dict)
        assert "modified_by" not in summary
        assert "created_by" not in summary
        # Null FKs should be skipped without triggering any queries
        assert len(ctx.captured_queries) == 0, (
            f"get_summary_fields() triggered {len(ctx.captured_queries)} queries for null FKs: " f"{[q['sql'] for q in ctx.captured_queries]}"
        )

    def test_summary_fields_no_lazy_load_with_select_related(self, system_user):
        """get_summary_fields() should not trigger per-FK lazy-load queries
        when the object was fetched with select_related."""
        user = User.objects.create(username="test-user")

        # Pre-load all FK relations so get_summary_fields() doesn't need to query
        user = User.objects.select_related("modified_by", "created_by", "resource").get(pk=user.pk)

        with CaptureQueriesContext(connection) as ctx:
            summary = user.get_summary_fields()

        assert isinstance(summary, dict)
        assert len(ctx.captured_queries) == 0, (
            f"get_summary_fields() triggered {len(ctx.captured_queries)} queries: " f"{[q['sql'] for q in ctx.captured_queries]}"
        )

    def test_summary_fields_content_unchanged(self, system_user):
        """get_summary_fields() should return the same content as before
        the optimization."""
        org = Organization.objects.create(name="test-org")
        team = Team.objects.create(name="test-team", organization=org)

        summary = team.get_summary_fields()

        # Organization FK should be in summary with expected structure
        assert "organization" in summary
        assert "id" in summary["organization"]
        assert "name" in summary["organization"]
        assert summary["organization"]["name"] == "test-org"
