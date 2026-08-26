"""Shared fixtures for the query-count-at-scale test suite.

This directory is targeted by its own CI job (see `.github/workflows/ci.yml`,
`py312-query-count-scale` tox env) so it can run in parallel without extending
the runtime of the main `tox` job matrix.

Tests here differ from the rest of `test_app/tests/` in two key ways (AAP-88875,
per Alan Rominger's guidance):

1. Instead of each test creating its own N objects inside a per-test DB transaction, a
   single broad dataset is seeded once per test *session* (see `_seed_large_dataset`
   below) and every test in this directory reuses it.
2. **Tests in this directory must NOT use `@pytest.mark.django_db` (or depend on the
   `db`/`transactional_db` fixtures directly).** Both of pytest-django's standard
   per-test isolation mechanisms are actively harmful here:
   - The default (`transaction=False`, i.e. the plain `django_db` marker) wraps every
     test in its own `atomic()` block, rolled back afterward. If the code path under
     test opens its *own* nested `atomic()` (common in this codebase -- e.g.
     `ansible_base/rbac/caching.py`'s permission-recomputation batches, used by
     `bulk_give_permissions()`), Django emits `SAVEPOINT`/`RELEASE SAVEPOINT`
     statements for that nesting. Those get counted by `CaptureQueriesContext` just
     like any other query, silently inflating the very query counts these tests exist
     to measure -- confirmed by direct experiment (nested `atomic()` under an outer
     `atomic()` adds a `SAVEPOINT`/`RELEASE SAVEPOINT` pair with no such statements
     when run unwrapped).
   - `transaction=True` avoids the SAVEPOINT problem, but pytest-django implements it
     by truncating all tables after *every* test -- which would erase the shared
     dataset below after the very first test in the session, defeating the whole
     "seed once, share across the run" design.

   Instead, `_unblocked_db` (autouse, session-scoped, below) uses the lower-level
   `django_db_blocker.unblock()` escape hatch -- the same primitive pytest-django uses
   internally, but without any of the atomic-wrapping/truncation machinery -- to permit
   DB access for the *entire* session. This is "pytest, but not pytest-django's test
   isolation": no test needs a `django_db`-family marker or fixture, and every query a
   test's request path makes is a real, uncoordinated statement against the live
   connection, just like a real production request would be.

   Consequence: nothing a test does here is rolled back or truncated. Prefer reusing
   the shared dataset/fixtures below over creating new objects; if a test does need to
   create something of its own, make it idempotent (`get_or_create`) or safely
   unique per test run, the same way `_seed_large_dataset` and the fixtures below
   guard themselves.

See epic AAP-88874 for full context, and AAP-88876 for the generalized, parameterized
query-count-cutoff coverage that consumes this seeded dataset.
"""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from test_app.management.commands.create_demo_data import Command
from test_app.models import Organization


@pytest.fixture(scope='session', autouse=True)
def _unblocked_db(request, django_db_blocker, django_db_use_migrations, django_db_keepdb, django_db_createdb):
    """Keep DB access unblocked for the whole test session (AAP-88875 follow-up).

    Deliberately does NOT request pytest-django's own `django_db_setup` fixture (the
    one `db`/`transactional_db` normally pull in). That fixture decides which database
    *aliases* to actually create/migrate/point-at-the-test-DB by scanning the session's
    collected test items for `django_db`-family markers (see
    `pytest_django.fixtures._get_databases_for_setup`) -- since nothing in this
    directory carries that marker (see module docstring for why), it would detect zero
    aliases needing setup, and every query would silently hit the real `default`
    database instead of a redirected `test_<name>` one. Confirmed by hitting exactly
    this: without this workaround, `Organization.objects.filter(...)` raised
    `relation "test_app_organization" does not exist` because the connection was still
    pointed at the real DB, not the test DB (`test_app_organization` did exist, but
    only inside the already-created `test_<name>` database).

    So this fixture calls Django's `setup_databases()`/`teardown_databases()` directly
    (the same call `django_db_setup` makes under the hood), hardcoding `aliases={'default'}`
    -- this project only has one database alias (see `test_app/defaults.py`) -- instead
    of relying on marker-based detection. `django_db_blocker.unblock()` only lifts
    pytest-django's "no DB access outside an opted-in fixture" guard; unlike
    `db`/`transactional_db`, it does not open an `atomic()` block or truncate anything
    on exit, so it's safe to hold open for the entire session.
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


@pytest.fixture(scope='session', autouse=True)
def _seed_large_dataset(_unblocked_db):
    """Seed a large, broad dataset once for the whole test session (AAP-88875).

    Runs with DB access unblocked for the whole session (see `_unblocked_db` above),
    outside of any per-test transaction, so the seeded data is committed once and
    persists for every test in this directory, instead of being created and rolled
    back per test.

    Calls `create_large()` directly (see `test_app/management/commands/create_demo_data.py`)
    rather than running the full `create_demo_data` command: `create_large()` alone covers
    orgs/teams/users/inventories/credentials/role-definitions with a mix of
    direct-object/org-level/team-mediated/mixed permission assignments, seeded via a single
    `bulk_give_permissions()` call. The rest of `create_demo_data` (fixed-name demo orgs, an
    OAuth2 application, and -- notably -- its own "Local Database Authenticator") is
    deliberately skipped: seeding a second enabled local authenticator here would collide
    with this directory's own `local_authenticator` fixture below (two enabled local
    authenticators makes username/password login ambiguous and login fails). Locally this
    takes ~13s for ~150 orgs/380 users/2,000 assignments -- comfortably under the ~1 minute
    CI budget Alan Rominger asked for.

    Idempotent: no-ops if `large_`-prefixed orgs already exist, so re-running this fixture
    (e.g. across multiple pytest invocations against a `--reuse-db` database) is safe and
    cheap.
    """
    if not Organization.objects.filter(name__startswith='large_').exists():
        Command().create_large(settings.DEMO_DATA_COUNTS)


@pytest.fixture(scope='session')
def local_authenticator(_unblocked_db):
    """Session-scoped, idempotent local counterpart to
    `ansible_base.lib.testing.fixtures.local_authenticator`.

    That fixture depends on `db` and unconditionally `.create()`s a new row every time
    it's requested -- safe there because pytest-django rolls back each test's
    transaction. Here, with no per-test rollback (see module docstring), a second
    `.create()` in a later test would hit a duplicate-name conflict, so this is
    `get_or_create()`'d once and shared for the whole session instead.
    """
    from ansible_base.authentication.models import Authenticator

    authenticator, _ = Authenticator.objects.get_or_create(
        name='Test Local Authenticator',
        defaults=dict(
            enabled=True,
            create_objects=True,
            remove_users=False,
            type='ansible_base.authentication.authenticator_plugins.local',
            configuration={},
        ),
    )
    return authenticator


@pytest.fixture(scope='session')
def admin_user(_unblocked_db):
    """Session-scoped, idempotent local counterpart to pytest-django's built-in
    `admin_user` fixture. Mirrors its get-or-create-a-superuser-named-"admin" logic,
    but calls `get_user_model()` directly instead of depending on pytest-django's
    `django_user_model`/`django_username_field` fixtures: those are function-scoped
    (via their own `db` dependency) and can't be requested from this session-scoped
    fixture, even though `get_user_model()` itself never touches the DB.
    """
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    username_field = user_model.USERNAME_FIELD
    username = 'admin@example.com' if username_field == 'email' else 'admin'
    try:
        return user_model._default_manager.get_by_natural_key(username)
    except user_model.DoesNotExist:
        user_data = {'password': 'password', username_field: username}
        if 'email' in user_model.REQUIRED_FIELDS:
            user_data['email'] = 'admin@example.com'
        return user_model._default_manager.create_superuser(**user_data)


@pytest.fixture(scope='session')
def admin_api_client(_unblocked_db, admin_user, local_authenticator):
    """Session-scoped local counterpart to
    `ansible_base.lib.testing.fixtures.admin_api_client` (which depends on `db`).
    Logs in once and reuses the same authenticated client for every test in the
    session instead of logging in/out per test.
    """
    # We don't use the is_staff flag anywhere. Instead we use is_superuser. This can
    # cause some permission checks to unexpectedly break in production where this flag
    # never gets set to true.
    admin_user.is_staff = False
    admin_user.save()
    client = APIClient()
    client.login(username='admin', password='password')
    return client
