"""Shared fixtures for the query-count-at-scale test suite.

This directory is targeted by its own CI job (see `.github/workflows/ci.yml`,
`py312-query-count-scale` tox env) so it can run in parallel without extending
the runtime of the main `tox` job matrix.

Tests here are eventually expected to differ from the rest of `test_app/tests/` in
a key way: instead of relying on per-test DB transactions (`@pytest.mark.django_db`)
for isolation, they'll share a single, broad dataset seeded once per test run. That
shared seeding fixture is tracked separately (AAP-88875) and will live in this file
once implemented; until then, tests here seed their own small datasets inline (still
using `@pytest.mark.django_db`), same as `test_resource_list_query_count.py`.

See epic AAP-88874 for full context, and AAP-88876 for the generalized,
parameterized version of the query-count-cutoff coverage started here.
"""
