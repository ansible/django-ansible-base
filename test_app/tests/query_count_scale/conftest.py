"""Shared fixtures for the query-count-at-scale test suite.

This directory is targeted by its own CI job (see `.github/workflows/ci.yml`,
`py312-query-count-scale` tox env) so it can run in parallel without extending
the runtime of the main `tox` job matrix.

Tests here differ from the rest of `test_app/tests/` in a key way: instead of each
test creating its own N objects inside a per-test DB transaction, a single broad
dataset is seeded once per test *session* (see `_seed_large_dataset` below, AAP-88875)
and every test in this directory reuses it. Individual tests still use
`@pytest.mark.django_db` for DB access and isolation of whatever they create on top of
the shared dataset, but they should not need to create bulk data themselves.

See epic AAP-88874 for full context, and AAP-88876 for the generalized, parameterized
query-count-cutoff coverage that consumes this seeded dataset.
"""

import pytest
from django.conf import settings

from test_app.management.commands.create_demo_data import Command
from test_app.models import Organization


@pytest.fixture(scope='session', autouse=True)
def _seed_large_dataset(django_db_setup, django_db_blocker):
    """Seed a large, broad dataset once for the whole test session (AAP-88875).

    Runs outside of any per-test transaction (via `django_db_blocker.unblock()`, the
    documented pytest-django pattern for session-scoped DB setup) so the seeded data is
    committed once and persists for every test in this directory, instead of being
    created and rolled back per test.

    Calls `create_large()` directly (see `test_app/management/commands/create_demo_data.py`)
    rather than running the full `create_demo_data` command: `create_large()` alone covers
    orgs/teams/users/inventories/credentials/role-definitions with a mix of
    direct-object/org-level/team-mediated/mixed permission assignments, seeded via a single
    `bulk_give_permissions()` call. The rest of `create_demo_data` (fixed-name demo orgs, an
    OAuth2 application, and -- notably -- its own "Local Database Authenticator") is
    deliberately skipped: seeding a second enabled local authenticator here would collide
    with the per-test `local_authenticator`/`admin_api_client` fixtures used throughout the
    test suite (two enabled local authenticators makes username/password login ambiguous
    and login fails). Locally this takes ~13s for ~150 orgs/380 users/2,000 assignments --
    comfortably under the ~1 minute CI budget Alan Rominger asked for.

    Idempotent: no-ops if `large_`-prefixed orgs already exist, so re-running this fixture
    (e.g. across multiple pytest invocations against a `--reuse-db` database) is safe and
    cheap.
    """
    with django_db_blocker.unblock():
        if not Organization.objects.filter(name__startswith='large_').exists():
            Command().create_large(settings.DEMO_DATA_COUNTS)
