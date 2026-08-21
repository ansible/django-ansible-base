"""Shared fixtures for the query-count-at-scale test suite.

This directory is targeted by its own CI job (see `.github/workflows/ci.yml`,
`py312-query-count-scale` tox env) so it can run in parallel without extending
the runtime of the main `tox` job matrix.

Tests here are expected to differ from the rest of `test_app/tests/` in a key way:
instead of relying on per-test DB transactions (`@pytest.mark.django_db`) for
isolation, they share a single, broad dataset seeded once per test run. That
seeding fixture is tracked separately (AAP-88875) and will live in this file once
implemented. Because there's no per-test rollback, tests that consume it must be
read-only (GET requests) against the seeded data.

See epic AAP-88874 for full context, and AAP-88876 for the query-count-cutoff
test coverage that will be added here.
"""
