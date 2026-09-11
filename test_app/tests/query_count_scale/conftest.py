"""Shared fixtures for the query-count-at-scale test suite.

Runs as its own CI job (`py312-query-count-scale` tox env, see
`.github/workflows/ci.yml`) in parallel with the main `tox` matrix, so it
doesn't add to that job's runtime.

Two differences from the rest of `test_app/tests/` (AAP-88875, per Alan
Rominger's guidance):

1. A single large dataset is seeded once per test *session* (see
   `_seed_large_dataset` below) instead of each test creating its own objects.
2. Tests here must NOT use `@pytest.mark.django_db` or the `db`/
   `transactional_db` fixtures. Both of pytest-django's isolation modes are
   harmful here: the default wraps each test in an `atomic()` block, and any
   nested `atomic()` in the code under test (e.g. `bulk_give_permissions()`'s
   permission-recomputation batches) emits extra `SAVEPOINT` queries that
   `CaptureQueriesContext` counts, inflating the exact numbers we're trying to
   measure. `transaction=True` avoids that, but truncates all tables after
   every test, wiping out the shared dataset. Instead, `_unblocked_db` below
   uses `django_db_blocker.unblock()` to allow real, uncoordinated DB access
   for the whole session. Nothing is rolled back or truncated, so any test
   that creates its own data must make it idempotent (`get_or_create`), the
   same way `_seed_large_dataset` does.

`_unblocked_db`/`_seed_large_dataset` are deliberately NOT `autouse`: an
`autouse` fixture runs for every test *collected* under a directory, not just
tests that request it, so a broad `pytest` invocation elsewhere could still
trigger the seeding. Tests must explicitly request `_seed_large_dataset` (or a
fixture that depends on it, e.g. `admin_api_client` below).

See epic AAP-88874 for full context, and AAP-88876 for the generalized,
parameterized query-count-cutoff coverage that consumes this seeded dataset.
"""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from test_app.management.commands.create_demo_data import Command
from test_app.models import Organization


@pytest.fixture(scope='session')
def _unblocked_db(request, django_db_blocker, django_db_use_migrations, django_db_keepdb, django_db_createdb):
    """Keep DB access unblocked for the whole test session (AAP-88875 follow-up).

    Doesn't use pytest-django's `django_db_setup` fixture: that fixture only sets
    up DB aliases for tests carrying a `django_db`-family marker (see module
    docstring for why nothing here has one), so it would detect nothing to set
    up and queries would silently hit the real `default` database instead of a
    redirected `test_<name>` one. Instead, this calls Django's
    `setup_databases()`/`teardown_databases()` directly -- what `django_db_setup`
    does internally -- hardcoded to `aliases={'default'}` since this project
    only has one DB alias.

    `django_db_blocker.unblock()` only lifts pytest-django's "no DB access
    outside an opted-in fixture" guard; unlike `db`/`transactional_db`, it
    doesn't open an `atomic()` block or truncate anything on exit, so it's safe
    to hold open for the whole session.
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
    """Seed a large, broad dataset once for the whole test session (AAP-88875).

    Runs outside any per-test transaction (see `_unblocked_db` above), so the
    data is committed once and reused by every test that requests it, instead
    of being created and rolled back per test.

    "Once per session" means once per `pytest` process -- this directory's own
    isolated `query-count-scale` CI job, with its own runner and DB container
    (see module docstring). It never touches the main `tox` job's test matrix,
    which also `--ignore`s this directory.

    Calls `create_large()` (see `create_demo_data.py`) rather than the full
    `create_demo_data` command, since the latter also seeds its own enabled
    local authenticator, which would collide with `local_authenticator` below.
    `create_large()` alone still covers orgs/teams/users/inventories/
    credentials/role-definitions with a mix of direct/org-level/team-mediated
    permission assignments.

    Idempotent: no-ops if `large_`-prefixed orgs already exist, so it's safe
    to rerun across multiple `--reuse-db` invocations. Locally takes ~13s for
    ~150 orgs/380 users/2,000 assignments, comfortably under the ~1 minute CI
    budget.
    """
    if not Organization.objects.filter(name__startswith='large_').exists():
        Command().create_large(settings.DEMO_DATA_COUNTS)


@pytest.fixture(scope='session')
def local_authenticator(_unblocked_db):
    """Session-scoped, idempotent counterpart to
    `ansible_base.lib.testing.fixtures.local_authenticator`, which unconditionally
    `.create()`s a new row per test -- safe there because pytest-django rolls
    back each test's transaction. Nothing is rolled back here (see module
    docstring), so this is `get_or_create()`'d once and shared for the session.
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
    """Session-scoped, idempotent counterpart to pytest-django's `admin_user`
    fixture: same get-or-create-a-superuser-named-"admin" logic, but calls
    `get_user_model()` directly instead of pytest-django's `django_user_model`,
    which is function-scoped (via `db`) and can't be used from here.
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
    """Session-scoped counterpart to
    `ansible_base.lib.testing.fixtures.admin_api_client`. Logs in once and
    reuses the same client for every test in the session, instead of logging
    in/out per test.
    """
    # We don't use the is_staff flag anywhere. Instead we use is_superuser. This can
    # cause some permission checks to unexpectedly break in production where this flag
    # never gets set to true.
    admin_user.is_staff = False
    admin_user.save()
    client = APIClient()
    client.login(username='admin', password='password')
    return client
