"""Nox configuration for django-ansible-base.

Replaces tox for test execution, linting, and Docker lifecycle management.
Session names match the legacy tox environment names.

Usage examples:
    nox -s py312                    # Run main test suite (Python 3.12)
    nox -s py311                    # Run main test suite (Python 3.11)
    nox -s py312-check              # Django check + migration check
    nox -s py312-sqlite             # Run tests with SQLite backend
    nox -s py312-django4            # Run tests pinned to Django 4.2
    nox -s py312-in-files           # Run tests using .in requirement files
    nox -s flake8                   # Run flake8 linter
    nox -s black                    # Run black formatter
    nox -s isort                    # Run isort import sorter
    nox -s lint                     # Run all linters
    nox -s stop_db                  # Stop the test postgres container (if still running)
"""

import os
import subprocess
import time

import nox

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POSTGRES_CONTAINER_NAME = "dab-test-postgres"
POSTGRES_IMAGE_NAME = "dab-test-postgres:latest"
POSTGRES_PORT = 55432
POSTGRES_DOCKERFILE = "tools/dev_postgres/Dockerfile"
POSTGRES_HEALTH_TIMEOUT = 60  # seconds

PYTHON_VERSIONS = ["3.11", "3.12"]

REQUIREMENTS_ALL = "requirements/requirements_all.txt"
REQUIREMENTS_DEV = "requirements/requirements_dev.txt"

PYTEST_CMD = [
    "pytest",
    "-n", "auto",
    "--color=yes",
    "--cov=.",
    "--cov-report=xml:coverage.xml",
    "--cov-report=html",
    "--cov-report=json",
    "--cov-branch",
    "--junit-xml=django-ansible-base-test-results.xml",
]

IN_FILE_REQUIREMENTS = [
    "requirements/requirements.in",
    "requirements/requirements_activitystream.in",
    "requirements/requirements_authentication.in",
    "requirements/requirements_api_documentation.in",
    "requirements/requirements_rest_filters.in",
    "requirements/requirements_rbac.in",
    "requirements/requirements_channels.in",
    "requirements/requirements_jwt_consumer.in",
    "requirements/requirements_redis_client.in",
    "requirements/requirements_oauth2_provider.in",
    "requirements/requirements_resource_registry.in",
    "requirements/requirements_feature_flags.in",
    "requirements/requirements_testing.txt",
    REQUIREMENTS_DEV,
]

# Default to reuse venvs for speed; CI can override with --no-reuse-existing-virtualenvs
nox.options.reuse_existing_virtualenvs = True


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def _is_container_running(name: str) -> bool:
    """Check if a Docker container with the given name is running."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _container_exists(name: str) -> bool:
    """Check if a Docker container with the given name exists (running or stopped)."""
    result = subprocess.run(
        ["docker", "inspect", name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _start_postgres(session: nox.Session) -> None:
    """Start a fresh PostgreSQL container for a test run.

    Any existing container with the same name is removed first to ensure
    a clean database state. The container is destroyed after the test run
    by ``_destroy_postgres``.
    """
    # Always remove any existing container to guarantee a clean database
    if _container_exists(POSTGRES_CONTAINER_NAME):
        session.log(f"Removing existing container '{POSTGRES_CONTAINER_NAME}'...")
        subprocess.run(["docker", "rm", "-f", POSTGRES_CONTAINER_NAME], check=True)

    # Build the image
    session.log("Building PostgreSQL Docker image...")
    subprocess.run(
        ["docker", "build", "-t", POSTGRES_IMAGE_NAME, "-f", POSTGRES_DOCKERFILE, os.path.dirname(POSTGRES_DOCKERFILE)],
        check=True,
    )

    # Run the container
    session.log(f"Starting PostgreSQL container on port {POSTGRES_PORT}...")
    subprocess.run(
        [
            "docker", "run",
            "-d",
            "--name", POSTGRES_CONTAINER_NAME,
            "-p", f"{POSTGRES_PORT}:5432",
            POSTGRES_IMAGE_NAME,
        ],
        check=True,
    )

    # Wait for healthy
    session.log("Waiting for PostgreSQL to become ready...")
    deadline = time.time() + POSTGRES_HEALTH_TIMEOUT
    while time.time() < deadline:
        result = subprocess.run(
            ["docker", "exec", POSTGRES_CONTAINER_NAME, "pg_isready", "-U", "dab", "-d", "dab_db"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            session.log("PostgreSQL is ready.")
            return
        time.sleep(1)

    session.error(f"PostgreSQL did not become ready within {POSTGRES_HEALTH_TIMEOUT}s")


def _destroy_postgres(session: nox.Session) -> None:
    """Stop and remove the PostgreSQL container."""
    if _container_exists(POSTGRES_CONTAINER_NAME):
        session.log(f"Destroying container '{POSTGRES_CONTAINER_NAME}'...")
        subprocess.run(["docker", "rm", "-f", POSTGRES_CONTAINER_NAME], check=True)


def _set_postgres_env(session: nox.Session) -> None:
    """Set environment variables so Django connects to the test postgres."""
    session.env["DB_HOST"] = "127.0.0.1"
    session.env["DB_PORT"] = str(POSTGRES_PORT)
    session.env["DB_USER"] = "dab"
    session.env["DB_PASSWORD"] = "dabing"
    session.env["DB_NAME"] = "dab_db"


def _pytest_args(session: nox.Session) -> list[str]:
    """Build the full pytest argument list, incorporating env vars and posargs."""
    args = list(PYTEST_CMD)

    extra = os.environ.get("ANSIBLE_BASE_PYTEST_ARGS", "")
    if extra:
        args.extend(extra.split())

    test_dirs = os.environ.get("ANSIBLE_BASE_TEST_DIRS", "test_app/tests")
    args.append(test_dirs)

    if session.posargs:
        args.extend(session.posargs)

    return args


# ---------------------------------------------------------------------------
# Test session implementations
# ---------------------------------------------------------------------------


def _run_tests(session: nox.Session) -> None:
    """Run the main test suite with PostgreSQL."""
    _start_postgres(session)
    try:
        _set_postgres_env(session)
        session.install("-r", REQUIREMENTS_ALL, "-r", REQUIREMENTS_DEV)
        session.run(*_pytest_args(session))
    finally:
        _destroy_postgres(session)


def _run_check(session: nox.Session) -> None:
    """Run Django system checks and verify no pending migrations."""
    _start_postgres(session)
    try:
        _set_postgres_env(session)
        session.install("-r", REQUIREMENTS_ALL, "-r", REQUIREMENTS_DEV)
        session.run("python3", "manage.py", "check")
        session.run("python3", "manage.py", "makemigrations", "--check")
    finally:
        _destroy_postgres(session)


def _run_tests_sqlite(session: nox.Session) -> None:
    """Run the test suite with SQLite backend."""
    _start_postgres(session)
    try:
        _set_postgres_env(session)
        session.env["DJANGO_SETTINGS_MODULE"] = "test_app.sqlite3settings"
        session.install("-r", REQUIREMENTS_ALL, "-r", REQUIREMENTS_DEV)
        session.run(*_pytest_args(session))
    finally:
        _destroy_postgres(session)


def _run_tests_django4(session: nox.Session) -> None:
    """Run the test suite pinned to Django 4.2."""
    _start_postgres(session)
    try:
        _set_postgres_env(session)
        session.install("-r", REQUIREMENTS_ALL, "-r", REQUIREMENTS_DEV)
        session.install("--upgrade", "Django>=4.2.21,<4.3.0")
        session.run(*_pytest_args(session))
    finally:
        _destroy_postgres(session)


def _run_tests_in_files(session: nox.Session) -> None:
    """Run the test suite using individual .in requirement files."""
    _start_postgres(session)
    try:
        _set_postgres_env(session)
        install_args = []
        for req in IN_FILE_REQUIREMENTS:
            install_args.extend(["-r", req])
        session.install(*install_args)
        session.run(*_pytest_args(session))
    finally:
        _destroy_postgres(session)


# ---------------------------------------------------------------------------
# Register test sessions with tox-compatible names (py311, py312-check, etc.)
# ---------------------------------------------------------------------------

# Mapping of suffix -> implementation function.
# Empty string suffix means the base session (e.g. "py311", "py312").
_TEST_VARIANTS = {
    "": _run_tests,
    "-check": _run_check,
    "-sqlite": _run_tests_sqlite,
    "-django4": _run_tests_django4,
    "-in-files": _run_tests_in_files,
}

for _py_version in PYTHON_VERSIONS:
    _py_tag = f"py{_py_version.replace('.', '')}"

    for _suffix, _impl in _TEST_VARIANTS.items():
        _session_name = f"{_py_tag}{_suffix}"

        # Use default arguments to capture loop variables by value
        def _make_session(_name=_session_name, _python=_py_version, _fn=_impl):
            @nox.session(name=_name, python=_python)
            def _session(session: nox.Session) -> None:
                _fn(session)

            _session.__doc__ = _fn.__doc__

        _make_session()


# ---------------------------------------------------------------------------
# Lint sessions
# ---------------------------------------------------------------------------


@nox.session(python="3.12", reuse_venv=True)
def flake8(session: nox.Session) -> None:
    """Run flake8 linter."""
    session.install("flake8==7.1.1", "Flake8-pyproject==1.2.3")
    args = session.posargs or ["."]
    session.run("flake8", *args)


@nox.session(python="3.12", reuse_venv=True)
def black(session: nox.Session) -> None:
    """Run black code formatter."""
    session.install("black==25.1.0")
    args = session.posargs or ["."]
    session.run("black", "--version")
    session.run("black", *args)


@nox.session(python="3.12", reuse_venv=True)
def isort(session: nox.Session) -> None:
    """Run isort import sorter."""
    session.install("isort==6.0.0")
    args = session.posargs or ["."]
    session.run("isort", *args)


@nox.session(python="3.12", reuse_venv=True)
def lint(session: nox.Session) -> None:
    """Run all linters (flake8, black --check, isort --check)."""
    session.install("flake8==7.1.1", "Flake8-pyproject==1.2.3", "black==25.1.0", "isort==6.0.0")
    session.run("flake8", ".")
    session.run("black", "--check", ".")
    session.run("isort", "--check", ".")


# ---------------------------------------------------------------------------
# Utility sessions
# ---------------------------------------------------------------------------


@nox.session(python=False)
def stop_db(session: nox.Session) -> None:
    """Stop and remove the test PostgreSQL container (if still running)."""
    _destroy_postgres(session)
