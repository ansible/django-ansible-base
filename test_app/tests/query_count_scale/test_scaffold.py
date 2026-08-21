"""Placeholder test for the query-count-scale CI job (AAP-88856).

This directory doesn't have real query-count coverage yet -- that lands in
follow-on stories (AAP-88875 for shared data seeding, AAP-88876 for the actual
query-count-cutoff tests). This placeholder just keeps the dedicated CI job
green (pytest exits non-zero if a target directory collects zero tests) until
that coverage exists.

Delete this file once test_query_count_scale/ has real tests.
"""

import pytest


@pytest.mark.django_db
def test_query_count_scale_job_is_wired_up():
    """Sanity check that this directory is collected and runs against a real DB."""
    from test_app.models import Organization

    assert Organization.objects.count() == 0
