# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Install dependencies
```bash
pip install -r requirements/requirements_all.txt
pip install -r requirements/requirements_dev.txt
```

### Start the dev environment
```bash
make postgres          # start Postgres container
python manage.py migrate
python manage.py createsuperuser  # username must be 'admin'
python manage.py authenticators --initialize
python manage.py runserver        # serves on http://127.0.0.1:8000/
```

Or use the bootstrap script (starts Postgres automatically, ephemeral — data is lost when the container stops):
```bash
./test_app/scripts/bootstrap.sh
```

### Run tests
```bash
make postgres         # Postgres must be running first
pytest test_app/tests # run all tests
pytest test_app/tests/rbac          # run tests for a specific app
pytest test_app/tests/rbac/test_access_control.py::TestSomething  # run a single test
pytest test_app/tests -k "test_name_pattern"  # filter by name

# SQLite variant (no Postgres needed):
DJANGO_SETTINGS_MODULE=test_app.sqlite3settings pytest test_app/tests
```

### Run via tox (as CI does)
```bash
make check            # full tox suite
tox -e py312          # single environment
tox -m lint           # lint only
```

### Lint
```bash
make lint             # flake8 + black + isort
make check_flake8
make check_black
make check_isort
```

### Migrations
```bash
python manage.py makemigrations <app_name>   # e.g., rbac, authentication
```

## Architecture

`django-ansible-base` is a **shared Django library** consumed by AWX, metrics-service, and other AAP Django services. It provides optional, independently-installable apps and utilities.

### Layout

```
ansible_base/        # all reusable code lives here
  <app_name>/        # each top-level folder (except lib/) is a Django app
  lib/               # pure shared utilities — not a Django app

test_app/            # self-contained Django project used only for testing
  tests/             # mirrors ansible_base/ structure; all tests live here
  settings.py        # test settings (Postgres)
  sqlite3settings.py # test settings (SQLite)
```

### The apps

Each app under `ansible_base/` is independently installable in a consumer's `INSTALLED_APPS`:

| App | Purpose |
|-----|---------|
| `activitystream` | Audit trail for model changes |
| `api_documentation` | OpenAPI/Swagger via drf-spectacular |
| `authentication` | Pluggable authenticator system (LDAP, SAML, social auth, local) |
| `feature_flags` | Feature flag management (django-flags) |
| `help_text_check` | Enforces `help_text` on model fields |
| `jwt_consumer` | JWT token consumer/validator for inter-service auth |
| `oauth2_provider` | OAuth2 provider (django-oauth-toolkit wrapper) |
| `observability` | OpenTelemetry / OTLP tracing |
| `prometheus` | Prometheus metrics endpoint |
| `rbac` | Role-Based Access Control engine |
| `resource_registry` | Cross-service resource tracking (uses Django Channels) |
| `rest_filters` | DRF filter backends |
| `rest_pagination` | DRF pagination classes |

### `ansible_base/lib/`

Shared utilities consumed by other modules in the library. Not a Django app. Key submodules:
- `dynamic_config/` — Dynaconf-based settings factory
- `testing/` — fixtures and utilities for consumers of this library
- `utils/` — general helpers

### App conventions

- **URL routing**: Apps expose `api_version_urls`, `api_urls`, and/or `root_urls` in their `urls.py`, loaded by the dynamic URL loader.
- **Views**: All views inherit from `ansible_base.lib.utils.views.AnsibleBaseDjangoAppApiView`.
- **App label**: Each app's `AppConfig` sets `label = 'dab_<app_name>'` to avoid clashes.
- **New feature decision**: Use a Django app if the feature needs models, URLs, management commands, or settings; otherwise add it to `ansible_base/lib/`.
- **Tests**: Tests are never placed in `ansible_base/`. All tests live in `test_app/tests/<app_name>/`.

### Optional extras

Each app has its own pip extra for scoped installs. Install all with `pip install -e ".[all]"` or individually, e.g., `pip install -e ".[rbac,authentication]"`.

### Settings

`pyproject.toml` contains all tool config: pytest, tox, flake8, black, isort.
- Line length: 160
- `isort` profile: `black`
- `black` `skip-string-normalization = true`
- Linters skip migration files
