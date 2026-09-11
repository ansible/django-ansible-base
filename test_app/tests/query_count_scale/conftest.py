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
`admin_api_client`).

The small `_seed_oauth_*`/`_seed_authenticator_maps` fixtures below are each
~30 cheap single-row `.create()` calls (no signals/permission recompute) --
negligible against the CI time budget.

See AAP-88874 for context, AAP-88876 for the query-count-cutoff tests that
consume this dataset.
"""

from datetime import datetime, timezone

import pytest
from django.conf import settings
from oauthlib.common import generate_token
from rest_framework.test import APIClient

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
    `local_authenticator` below). Covers orgs/teams/users/inventories/
    credentials/role-definitions with direct/org-level/team-mediated
    assignments.

    Idempotent (no-ops if `large_`-prefixed orgs exist) -- safe to rerun with
    `--reuse-db`. ~13s locally for ~150 orgs/380 users/2,000 assignments,
    comfortably under CI's ~1 minute budget.
    """
    if not Organization.objects.filter(name__startswith='large_').exists():
        Command().create_large(settings.DEMO_DATA_COUNTS)


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
def _seed_oauth_tokens(_seed_large_dataset, admin_user):
    """Seed 30 OAuth2 access tokens once per session (AAP-88874) -- needed for
    `token-list`. Idempotent: no-ops if `large_token_`-prefixed rows exist.
    """
    if not OAuth2AccessToken.objects.filter(description__startswith='large_token_').exists():
        for i in range(30):
            OAuth2AccessToken.objects.create(
                user=admin_user,
                token=generate_token(),
                scope='read write',
                expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
                description=f'large_token_{i}',
            )


@pytest.fixture(scope='session')
def _seed_authenticator_maps(_seed_large_dataset, local_authenticator):
    """Seed 30 authenticator maps once per session (AAP-88874) -- needed for
    `authenticatormap-list`. Idempotent: no-ops if `large_map_`-prefixed rows exist.
    """
    from ansible_base.authentication.models import AuthenticatorMap

    if not AuthenticatorMap.objects.filter(name__startswith='large_map_').exists():
        for i in range(30):
            AuthenticatorMap.objects.create(
                name=f'large_map_{i}',
                authenticator=local_authenticator,
                map_type='allow',
            )


@pytest.fixture(scope='session')
def local_authenticator(_unblocked_db):
    """Session-scoped, idempotent counterpart to
    `ansible_base.lib.testing.fixtures.local_authenticator`, which
    unconditionally `.create()`s a row per test -- safe there since
    pytest-django rolls back each test's transaction. Nothing is rolled back
    here, so this is `get_or_create()`'d once and shared for the session.
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
    """Session-scoped, idempotent counterpart to pytest-django's `admin_user`:
    same get-or-create-a-superuser-named-"admin" logic, but calls
    `get_user_model()` directly since `django_user_model` is function-scoped
    (via `db`) and can't be used here.
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
    `ansible_base.lib.testing.fixtures.admin_api_client`: logs in once and
    reuses the same client for every test, instead of per-test login/logout.
    """
    # We don't use the is_staff flag anywhere. Instead we use is_superuser. This can
    # cause some permission checks to unexpectedly break in production where this flag
    # never gets set to true.
    admin_user.is_staff = False
    admin_user.save()
    client = APIClient()
    client.login(username='admin', password='password')
    return client
