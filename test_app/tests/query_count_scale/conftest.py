"""Shared fixtures for the query-count-at-scale test suite.

Runs as its own CI job (`py312-query-count-scale` tox env) in parallel with
the main tox matrix, so it adds no runtime there (AAP-88856/AAP-88875).

Two differences from the rest of `test_app/tests/`:
1. One large dataset is seeded once per session (`_seed_large_dataset`),
   reused by every test instead of created per-test.
2. No `@pytest.mark.django_db`/`db`/`transactional_db` here -- both wrap
   tests in extra `atomic()`/`SAVEPOINT` machinery that would inflate the
   query counts being measured. `_unblocked_db` below unblocks real,
   session-long DB access instead. Nothing is rolled back or truncated, so
   any fixture that creates data must be idempotent (`get_or_create`, or a
   `.filter(...).exists()` guard), same as `_seed_large_dataset`.

None of these fixtures are `autouse` (that would run them for every test
*collected* under this directory, not just ones that need them) -- tests
must request them explicitly, or a fixture that depends on them (e.g.
`session_admin_api_client`).

The small `_seed_oauth_*`/`_seed_authenticator_maps` fixtures below are each
~30 cheap single-row `.create()` calls (no signals/permission recompute) --
negligible against the CI time budget.

See AAP-88874 for context, AAP-88876 for the query-count-cutoff tests that
consume this dataset.
"""

from datetime import datetime, timezone

import pytest
from django.conf import settings
from django.db import transaction
from oauthlib.common import generate_token

from ansible_base.lib.testing.fixtures import _get_or_create_admin_user, _get_or_create_local_authenticator, _login_admin_api_client
from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2Application
from test_app.management.commands.create_demo_data import Command
from test_app.models import Organization


@pytest.fixture(scope='session')
def _unblocked_db(request, django_db_blocker, django_db_use_migrations, django_db_keepdb, django_db_createdb):
    """Keep DB access unblocked for the whole session (AAP-88875).

    Calls Django's `setup_databases()`/`teardown_databases()` directly --
    what pytest-django's `django_db_setup` does internally -- since that
    fixture only activates for tests carrying a `django_db`-family marker,
    none of which exist here (see module docstring).

    `django_db_blocker.unblock()` just lifts pytest-django's "no DB access"
    guard; unlike `db`/`transactional_db` it doesn't open an `atomic()` block
    or truncate anything on exit, so it's safe to hold open all session.
    """
    from django.test.utils import setup_databases, teardown_databases

    if not django_db_use_migrations:
        from pytest_django.fixtures import _disable_migrations

        _disable_migrations()

    setup_databases_kwargs = {}
    if django_db_keepdb and not django_db_createdb:
        setup_databases_kwargs['keepdb'] = True

    with django_db_blocker.unblock():
        db_cfg = setup_databases(
            verbosity=request.config.option.verbose,
            interactive=False,
            aliases={'default'},
            **setup_databases_kwargs,
        )
        yield
        if not django_db_keepdb:
            try:
                teardown_databases(db_cfg, verbosity=request.config.option.verbose)
            except Exception as exc:  # pragma: no cover -- mirrors django_db_setup's own handling
                request.node.warn(pytest.PytestWarning(f"Error when trying to teardown test databases: {exc!r}"))


@pytest.fixture(scope='session')
def _seed_large_dataset(_unblocked_db):
    """Seed a large, broad dataset once for the whole session (AAP-88875).

    Calls `create_large()` rather than the full `create_demo_data` command
    (which also enables its own local authenticator, colliding with
    `session_local_authenticator` below). Covers orgs/teams/users/inventories/
    credentials/role-definitions with direct/org-level/team-mediated
    assignments.

    Idempotent (validates all expected counts match DEMO_DATA_COUNTS before
    skipping) -- safe to rerun with `--reuse-db`. Wrapped in transaction.atomic()
    so partial writes roll back on failure. ~13s locally for ~150 orgs/380 users/
    2,000 assignments, comfortably under CI's ~1 minute budget.
    """
    from django.contrib.auth import get_user_model

    from ansible_base.rbac.models import RoleDefinition
    from test_app.models import Credential, Inventory, Team

    # Check if seeding already completed successfully by validating all expected counts.
    # Checked per-model (not just "does 1 row exist") so a --reuse-db database that
    # predates a DEMO_DATA_COUNTS key being added doesn't silently skip reseeding forever.
    expected = settings.DEMO_DATA_COUNTS
    actual_counts = {
        'organization': Organization.objects.filter(name__startswith='large_').count(),
        'user': get_user_model().objects.filter(username__startswith='large_user_').count(),
        'team': Team.objects.filter(name__startswith='large_team_').count(),
        'roledefinition': RoleDefinition.objects.filter(name__startswith='Large Role Definition').count(),
        'inventory': Inventory.objects.filter(name__startswith='large_inventory_').count(),
        'credential': Credential.objects.filter(name__startswith='large_credential_').count(),
    }

    # Fail loudly (not silently skip) if DEMO_DATA_COUNTS ever gains a key with no
    # corresponding count check above -- same bug class this fixed for `credential`.
    missing = expected.keys() - actual_counts.keys()
    assert not missing, (
        f"DEMO_DATA_COUNTS has keys with no corresponding count check in _seed_large_dataset: "
        f"{sorted(missing)}. Add a query for each new resource type above."
    )

    # Skip seeding if every count already matches
    if all(actual_counts[key] == count for key, count in expected.items()):
        return

    # Seed atomically (all-or-nothing) so crashes leave no partial junk behind
    with transaction.atomic():
        Command().create_large(expected)


@pytest.fixture(scope='session')
def _seed_oauth_applications(_seed_large_dataset):
    """Seed 30 OAuth2 applications once per session (AAP-88874) -- `create_large()`
    doesn't create any, so `application-list` needs its own data. Idempotent:
    no-ops if `large_app_`-prefixed rows already exist.
    """
    if not OAuth2Application.objects.filter(name__startswith='large_app_').exists():
        org = Organization.objects.filter(name__startswith='large_').first()
        for i in range(30):
            OAuth2Application.objects.create(
                name=f'large_app_{i}',
                description='Seeded for query-count-scale coverage (AAP-88874)',
                redirect_uris='https://example.com/callback',
                authorization_grant_type='authorization-code',
                client_type='confidential',
                organization=org,
            )


@pytest.fixture(scope='session')
def _seed_oauth_tokens(_seed_large_dataset, session_admin_user):
    """Seed 30 OAuth2 access tokens once per session (AAP-88874) -- needed for
    `token-list`. Idempotent: no-ops if `large_token_`-prefixed rows exist.
    """
    if not OAuth2AccessToken.objects.filter(description__startswith='large_token_').exists():
        for i in range(30):
            OAuth2AccessToken.objects.create(
                user=session_admin_user,
                token=generate_token(),
                scope='read write',
                expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
                description=f'large_token_{i}',
            )


@pytest.fixture(scope='session')
def _seed_authenticator_maps(_seed_large_dataset, session_local_authenticator):
    """Seed 30 authenticator maps once per session (AAP-88874) -- needed for
    `authenticatormap-list`. Idempotent: no-ops if `large_map_`-prefixed rows exist.
    """
    from ansible_base.authentication.models import AuthenticatorMap

    if not AuthenticatorMap.objects.filter(name__startswith='large_map_').exists():
        for i in range(30):
            AuthenticatorMap.objects.create(
                name=f'large_map_{i}',
                authenticator=session_local_authenticator,
                map_type='allow',
            )


@pytest.fixture(scope='session')
def session_local_authenticator(_unblocked_db):
    """Session-scoped, shared-helper-backed counterpart to
    `ansible_base.lib.testing.fixtures.local_authenticator`. That one
    `.create()`s per test (safe there, since pytest-django rolls back each
    test's transaction); nothing is rolled back here, so this is created once
    and shared for the session.
    """
    return _get_or_create_local_authenticator()


@pytest.fixture(scope='session')
def session_admin_user(_unblocked_db):
    """Session-scoped, shared-helper-backed counterpart to pytest-django's
    `admin_user`. That one is a pytest-django built-in (no in-repo sibling to
    share a helper with), so `_get_or_create_admin_user()` normalizes any
    stale user surviving a `--reuse-db` run (active, superuser, password)
    since it's not re-created per test the way pytest-django's is.
    """
    from django.contrib.auth import get_user_model

    return _get_or_create_admin_user(get_user_model())


@pytest.fixture(scope='session')
def session_admin_api_client(_unblocked_db, session_admin_user, session_local_authenticator):
    """Session-scoped counterpart to
    `ansible_base.lib.testing.fixtures.admin_api_client`: logs in once and
    reuses the same client for every test, instead of per-test login/logout.
    Asserts login succeeds -- critical here (unlike the function-scoped
    fixture) since a stale user could otherwise silently fail to log in and
    every test would run unauthenticated.

    No test in this directory may call `.logout()` on this client -- it is
    shared for the whole session with no per-test reset, so a logout here
    would silently leave every later test unauthenticated. Use a throwaway
    `APIClient()` instead if a test needs to exercise logout.
    """
    client, login_ok = _login_admin_api_client(session_admin_user)
    assert login_ok, "session_admin_api_client login failed — tests would run as anonymous user"
    return client
