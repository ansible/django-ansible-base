"""Reusable query-count regression helpers.

`assert_query_count_flat` sweeps a list endpoint across a few page sizes and
asserts the query count doesn't grow -- an N+1's signature (one extra query
per row instead of a batched prefetch). This replaces hand-tuned,
per-endpoint `max_queries` cutoffs with one shared tolerance for every
endpoint: an endpoint is compared against itself, not a magic number.

Plain function, not a pytest fixture, so other django-ansible-base consumers
(Controller, Hub, EDA) can import and reuse it directly.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext

DEFAULT_PAGE_SIZES = (1, 10, 100)
DEFAULT_MAX_QUERY_DELTA = 3


def assert_query_count_flat(client, url, query_params=None, page_sizes=DEFAULT_PAGE_SIZES, max_query_delta=DEFAULT_MAX_QUERY_DELTA):
    """Assert requesting `url` at growing `page_size`s doesn't grow the query
    count by more than `max_query_delta` -- the N+1 signal, without a
    hand-picked per-endpoint cutoff.

    Each page size is requested twice (warm-up, then captured) so one-time
    costs like ContentType's cache don't skew the comparison. Also asserts
    every page is non-empty and that the largest page returns more rows than
    the smallest -- otherwise the seeded dataset is too small for the sweep
    to mean anything.
    """
    query_params = dict(query_params or {})
    counts = {}
    row_counts = {}

    for page_size in page_sizes:
        params = {**query_params, 'page_size': page_size}
        client.get(url, params)  # warm up (e.g. ContentType cache)
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url, params)

        assert response.status_code == 200, f"{url}?{params} returned {response.status_code}, expected 200."

        results = response.data['results']
        assert len(results) > 0, f"{url}?{params} returned an empty page; query-count comparison would be meaningless."

        counts[page_size] = len(ctx.captured_queries)
        row_counts[page_size] = len(results)

    smallest, largest = min(page_sizes), max(page_sizes)
    assert row_counts[largest] > row_counts[smallest], (
        f"{url}: page_size={largest} and page_size={smallest} both returned {row_counts[largest]} rows -- "
        f"seed more data for this endpoint, or lower the page sizes under test."
    )

    delta = max(counts.values()) - min(counts.values())
    assert delta <= max_query_delta, (
        f"{url} query count grew with page size, exceeding the tolerance of {max_query_delta}: "
        f"{', '.join(f'page_size={ps} -> {counts[ps]} queries ({row_counts[ps]} rows)' for ps in page_sizes)}. "
        f"Likely a per-row query (N+1) instead of a batched prefetch/select_related."
    )
