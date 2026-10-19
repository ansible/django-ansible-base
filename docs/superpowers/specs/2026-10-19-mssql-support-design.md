# MS SQL Server Support for django-ansible-base

**Date:** 2026-10-19  
**Status:** Design Approved  
**JIRA:** TBD (placeholder - ticket coming today)  
**Initiative:** [ANSTRAT-1887](https://redhat.atlassian.net/browse/ANSTRAT-1887) - Microsoft SQL Server Database Support - Technology Preview  
**Related:** ansible/metrics-service#477 (reference implementation), [SDP](../../../handbook/The%20Ansible%20Engineering%20Handbook/System-Design-Plans/ANSTRAT-1887-MS-SQL-Server-Database-Support---Technology-Preview.md)

## Overview

Add MS SQL Server 2025 (17.x) support to django-ansible-base as part of the **Technology Preview** for ANSTRAT-1887. This enables AAP components (Controller, Gateway, EDA, Metrics, Lightspeed) to use customer-provided, Windows-based Microsoft SQL Server instead of PostgreSQL. 

Implementation follows the proven metrics-service pattern: parallel `mssql_migrations/` directories for all 10 DAB apps, runtime migration selection based on `DATABASES['default']['ENGINE']`, database-specific implementations for PostgreSQL-only features (advisory locks, pg_notify), and a separate docker-compose setup for MS SQL development.

**Technology Preview Scope:**
- Fresh installations only (no upgrades, migrations, backups, or restores)
- Development and validation focused on core AAP functionality
- Full multi-node validation, performance/scale testing deferred to GA (ANSTRAT-1238)

## Goals

1. **Enable MS SQL Server 2025 support** for AAP components (Controller, Gateway, EDA, Metrics, Lightspeed) per ANSTRAT-1887
2. **Maintain backward compatibility** - existing PostgreSQL deployments completely unaffected
3. **Support fresh installations only** - migrations, upgrades, backups, and restores out of scope for Technology Preview
4. **Replace PostgreSQL-specific features** with MS SQL equivalents (advisory locks, dispatcher notifications)
5. **Provide development environment** for testing MS SQL Server integration

## Success Criteria (Aligned with ANSTRAT-1887)

**R4 - Core Functionality:**
- [ ] All 10 DAB apps have squashed `mssql_migrations/` that work on MS SQL Server 2025
- [ ] Test app starts successfully against local MS SQL Server 2025 container
- [ ] PostgreSQL-specific code replaced with MS SQL equivalents (advisory locks, notify params)
- [ ] No changes to existing PostgreSQL migrations

**R5 - Testing:**
- [ ] All DAB unit tests pass on both PostgreSQL and MS SQL Server
- [ ] Integration tests pass on MS SQL Server
- [ ] ATF test suites can run against MS SQL Server (consumer app validation)

**R6 - Documentation:**
- [ ] Installation and setup documentation complete
- [ ] Technology Preview limitations clearly documented
- [ ] Fresh install only, no migration/upgrade support emphasized

**P1 - PostgreSQL NOTIFY Replacement:**
- [ ] `get_sql_server_notify_params()` implemented for dispatcherd Service Broker configuration

## Non-Goals (Technology Preview Limitations)

**Out of scope per ANSTRAT-1887:**
- Upgrades to existing AAP installations (fresh install only)
- PostgreSQL to MS SQL Server migrations
- Database backend changes after installation
- Backup and restore functionality
- Full multi-node validation (deferred to ANSTRAT-1238 GA)
- Performance and scale testing (deferred to GA)
- Production-grade performance optimization (deferred to GA)
- MS SQL Server on Linux or in containers (Windows-based only)
- Azure SQL support (out of scope)
- SQLite or MySQL support (out of scope)
- Changing existing PostgreSQL migrations
- Full Service Broker implementation in DAB (consumer apps handle dispatcherd config)
- Hub and Portal MS SQL support (PostgreSQL only)

## ANSTRAT-1887 SDP Alignment

This design implements django-ansible-base support for the Technology Preview defined in [ANSTRAT-1887 SDP](../../../handbook/The%20Ansible%20Engineering%20Handbook/System-Design-Plans/ANSTRAT-1887-MS-SQL-Server-Database-Support---Technology-Preview.md).

### Requirements Coverage

| SDP Requirement | Design Implementation |
|-----------------|----------------------|
| **R1** - Install-time configuration | Migration selection via `ENGINE_MIGRATION_MAP` detects database at Django startup. Consumer apps set `DATABASES['default']['ENGINE']`. No post-install switching. |
| **R2** - Windows-based SQL Server 2025 validation | Docker dev environment uses SQL Server 2025. Design targets 2019+ compatibility per Q1 answer. |
| **R3** - Username/password auth with TLS/SSL | Dev environment uses basic auth. Production TLS requirements documented. `TrustServerCertificate=yes` marked as dev-only. |
| **R4** - Core functionality (Controller/Gateway/EDA/Metrics/Lightspeed) | All 10 DAB apps covered. Advisory locks, bulk operations, and notify params implemented for both databases. |
| **R5** - ATF testing validation | Phase 6 includes test infrastructure. Consumer apps run their ATF suites against DAB on MS SQL. |
| **R6** - Documentation and limitations | Comprehensive docs in `docs/mssql-support.md` emphasizing fresh install only, TP limitations, no migration/upgrade support. |
| **R7** - Support team briefing | Out of DAB scope (consumer apps handle). |

### Problem Statement P1 Coverage

**P1: Replace PostgreSQL notifications for task dispatch**

Design implements `get_sql_server_notify_params()` helper function that:
- Extracts MS SQL Server connection parameters from Django settings
- Supports `SQL_SERVER_NOTIFY_DATABASES` override (parallel to `PG_NOTIFY_DATABASES`)
- Returns pyodbc-compatible connection dict for dispatcherd Service Broker configuration
- Consumer apps (Controller, EDA) check `connection.vendor` and call appropriate helper
- Actual dispatcherd broker configuration happens in consumer apps, not DAB

This solves P1 by providing the database connection information consumer apps need to configure dispatcherd's `sql_server` broker, replacing the `pg_notify` broker dependency.

### Open Questions Addressed

**Q1: Customer-provided MS SQL Server contract**
- Design assumes SQL Server 2025 per SDP answer
- Uses ODBC Driver 18 for SQL Server
- Dev environment demonstrates required connection parameters
- Production certificate validation requirements documented but not implemented (consumer app concern)

**Q2: What must work across AAP components**
- All DAB apps support MS SQL Server
- Advisory locks preserve distributed locking semantics
- Bulk operations maintain correctness (performance acceptable per SDP scope)
- Migration selection ensures no PostgreSQL dependency in MS SQL mode

**Q3: Evidence and limitations**
- Phase 6 testing validates fresh install scenario
- Documentation clearly separates TP validation from deferred GA work
- Known limitations prominently documented

**Q4: Productization conditions**
- mssql-django and pyodbc added to DAB requirements
- ODBC driver installation documented as prerequisite
- Licensing/security review out of DAB scope (platform concern)

## Architecture

### Migration Selection Strategy

**Runtime Migration Module Selection:**
- Early AppConfig hook in `ansible_base/lib/apps.py` executes before any app's `ready()` method
- Inspects `settings.DATABASES['default']['ENGINE']`
- Sets `settings.MIGRATION_MODULES` to map each DAB app to either `migrations/` or `mssql_migrations/`

**Pattern (from metrics-service):**
```python
ENGINE_MIGRATION_MAP = {
    'mssql': 'mssql_migrations',
    # Future: other databases can be added here
}

default_database = settings.DATABASES.get("default", {})
engine = default_database.get("ENGINE", "")
migration_directory = ENGINE_MIGRATION_MAP.get(engine, "migrations")

# Only override if non-default
if migration_directory != "migrations":
    DAB_APPS = [
        "rbac", "resource_registry", "rest_filters", "rest_pagination",
        "activitystream", "api_documentation", "authentication", 
        "feature_flags", "jwt_consumer", "oauth2_provider"
    ]
    settings.MIGRATION_MODULES = {
        f"ansible_base.{app}": f"ansible_base.{app}.{migration_directory}"
        for app in DAB_APPS
    }
```

**Why this approach:**
- Consumer apps (controller, gateway, etc.) configure database engine before Django setup
- DAB detects the engine and loads correct migrations automatically
- No consumer-side migration configuration needed beyond setting `ENGINE`
- Proven pattern from metrics-service

### Directory Structure

```
ansible_base/
  lib/
    apps.py (NEW) - AnsibleBaseConfig with migration selection
    utils/
      db.py (MODIFIED) - Add MS SQL advisory locks, notify params
  
  rbac/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed, manually edited)
  
  resource_registry/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed, manually edited)
  
  rest_filters/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed)
  
  rest_pagination/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed)
  
  activitystream/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed)
  
  api_documentation/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed)
  
  authentication/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed)
  
  feature_flags/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed)
  
  jwt_consumer/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed)
  
  oauth2_provider/
    migrations/ (UNTOUCHED - PostgreSQL)
    mssql_migrations/ (NEW)
      __init__.py
      0001_initial.py (squashed)

test_app/
  mssqlsettings.py (NEW) - MS SQL test configuration
  scripts/
    bootstrap.sh (MODIFIED) - Support DB_BACKEND=mssql

docs/
  mssql-support.md (NEW) - MS SQL Server documentation
  superpowers/specs/
    2026-10-19-mssql-support-design.md (THIS FILE)

docker-compose.mssql.yml (NEW) - MS SQL Server 2025 container
Makefile (MODIFIED) - Add mssql targets
pyproject.toml (MODIFIED) - Add mssql-django, pyodbc
requirements/requirements.txt (MODIFIED) - Add mssql-django, pyodbc
```

## Database-Specific Code Replacements

### Advisory Locks (`ansible_base/lib/utils/db.py`)

**Current PostgreSQL implementation:**
- Uses `pg_advisory_lock()` / `pg_advisory_unlock()` SQL functions
- Provides distributed locking across processes/containers
- Used by RBAC system for cache recomputation

**MS SQL Server equivalent:**
- Use `sp_getapplock` / `sp_releaseapplock` stored procedures
- Similar semantics: session-scoped locks, shared/exclusive modes
- Lock ID transformation: PostgreSQL takes int/bigint, MS SQL takes nvarchar resource name

**Implementation approach:**
```python
@contextmanager
def advisory_lock(*args, lock_session_timeout_milliseconds=0, shared=False, wait=True, **kwargs):
    """Context manager for database advisory locks.
    
    Supported databases:
    - PostgreSQL: pg_advisory_lock
    - MS SQL Server: sp_getapplock
    - SQLite: no-op (returns True)
    """
    if connection.vendor == "postgresql":
        # Existing PostgreSQL implementation using pg_advisory_lock
        # (no changes)
        
    elif connection.vendor == "microsoft":
        # New MS SQL Server implementation
        lock_name = _convert_lock_id_to_resource_name(args[0])
        mode = 'Shared' if shared else 'Exclusive'
        timeout = lock_session_timeout_milliseconds if lock_session_timeout_milliseconds > 0 else -1
        
        cursor = connection.cursor()
        try:
            # sp_getapplock returns: 0=success, 1=granted after wait, -1=timeout, etc.
            cursor.execute(
                "DECLARE @result int; EXEC @result = sp_getapplock @Resource=%s, @LockMode=%s, @LockTimeout=%s; SELECT @result",
                [lock_name, mode, timeout]
            )
            result = cursor.fetchone()[0]
            
            if not wait and result < 0:
                acquired = False
            else:
                acquired = result >= 0
                
            try:
                yield acquired
            finally:
                if acquired:
                    cursor.execute("EXEC sp_releaseapplock @Resource=%s", [lock_name])
        finally:
            cursor.close()
            
    elif connection.vendor == "sqlite":
        # Existing SQLite stub
        yield True
        
    else:
        raise RuntimeError(f'Advisory lock not implemented for database type {connection.vendor}')


def _convert_lock_id_to_resource_name(lock_id):
    """Convert PostgreSQL-style lock ID to MS SQL resource name.
    
    PostgreSQL accepts integers, tuples of integers, or strings.
    MS SQL requires nvarchar resource names.
    """
    if isinstance(lock_id, str):
        return lock_id
    elif isinstance(lock_id, int):
        return f"dab_lock_{lock_id}"
    elif isinstance(lock_id, (list, tuple)):
        return f"dab_lock_{'_'.join(str(x) for x in lock_id)}"
    else:
        # Fall back to hash for other types
        from zlib import crc32
        return f"dab_lock_{crc32(str(lock_id).encode('utf-8'))}"
```

**Key differences:**
- PostgreSQL: Integer lock IDs, separate functions for shared/exclusive
- MS SQL: String resource names, mode parameter
- Timeout handling: PostgreSQL uses SET statements, MS SQL uses procedure parameter
- Return values differ: need to map MS SQL return codes to acquired boolean

### PostgreSQL NOTIFY/LISTEN Support

**Current usage:**
- `get_pg_notify_params()` - Returns psycopg connection params for LISTEN/NOTIFY
- Used by AWX/controller for dispatcherd pg_notify broker configuration
- Returns connection parameters from Django DATABASES with optional overrides

**MS SQL Server equivalent:**
Add parallel function `get_sql_server_notify_params()` for dispatcherd SQL Server broker:

```python
def get_sql_server_notify_params(alias: str = DEFAULT_DB_ALIAS, **extra_options) -> dict:
    """Returns connection parameters for MS SQL Server Service Broker (dispatcherd).
    
    Similar to get_pg_notify_params() but for MS SQL Server.
    Consumer apps use this to configure dispatcherd's sql_server broker.
    
    Supports override settings:
    - SQL_SERVER_NOTIFY_DATABASES: parallel to PG_NOTIFY_DATABASES
    
    Returns pyodbc-compatible connection dictionary.
    """
    sql_server_overrides = {}
    if hasattr(settings, 'SQL_SERVER_NOTIFY_DATABASES'):
        sql_server_overrides = settings.SQL_SERVER_NOTIFY_DATABASES.get(alias, {})
    
    settings_dict = combine_settings_dict(
        settings.DATABASES[alias], 
        sql_server_overrides, 
        **extra_options
    )
    
    # Extract pyodbc connection parameters
    params = {
        'server': settings_dict.get('HOST', 'localhost'),
        'port': settings_dict.get('PORT', 1433),
        'database': settings_dict.get('NAME'),
        'user': settings_dict.get('USER'),
        'password': settings_dict.get('PASSWORD'),
    }
    
    # Add OPTIONS if present (driver, extra_params, etc.)
    if 'OPTIONS' in settings_dict:
        params.update(settings_dict['OPTIONS'])
    
    return params
```

**Usage by consumer apps:**
```python
# In controller/gateway/EDA dispatcherd configuration
from django.db import connection
from ansible_base.lib.utils.db import get_pg_notify_params, get_sql_server_notify_params

if connection.vendor == "postgresql":
    broker_config = {
        "pg_notify": {
            "config": get_pg_notify_params(),
            "sync_connection_factory": "ansible_base.lib.utils.db.psycopg_connection_from_django",
        }
    }
elif connection.vendor == "microsoft":
    broker_config = {
        "sql_server": {
            "config": get_sql_server_notify_params(),
        }
    }
```

**Note:** The actual dispatcherd configuration changes happen in consumer apps (controller, gateway, etc.), not in DAB. DAB just provides the helper function.

### Bulk Create with Conflict Handling

**Issue:** mssql-django does not support `bulk_create(ignore_conflicts=True)`

**Solution:** Conditional fallback using `get_or_create` for MS SQL Server

**Implementation pattern:**
```python
def _bulk_create_ignore_conflicts(model, objects, unique_fields):
    """Create objects in bulk, handling conflicts based on database support.
    
    PostgreSQL: Uses bulk_create(ignore_conflicts=True) - fast single query
    MS SQL Server: Falls back to get_or_create per object - slower but works
    """
    if not objects:
        return
    
    if connection.features.supports_ignore_conflicts:
        # PostgreSQL path - fast bulk insert
        model.objects.bulk_create(objects, ignore_conflicts=True)
    else:
        # MS SQL Server path - individual get_or_create
        for obj in objects:
            lookup = {field: getattr(obj, field) for field in unique_fields}
            defaults = {
                field.name: getattr(obj, field.name)
                for field in model._meta.concrete_fields
                if not field.primary_key 
                and field.name not in unique_fields 
                and field.attname not in unique_fields
            }
            model.objects.get_or_create(**lookup, defaults=defaults)
```

**Locations to update:**
- `ansible_base/rbac/caching.py`:
  - `_bulk_create_evaluations()` - RoleEvaluation/RoleEvaluationUuid creation
- `ansible_base/rbac/pipeline.py`:
  - `_ensure_object_roles()` - ObjectRole creation
  - `_create_assignments()` - RoleUserAssignment and RoleTeamAssignment creation

**Performance note:** MS SQL Server path is slower (N queries vs 1), but:
- Acceptable for MS SQL deployments (not performance-critical path)
- Maintains correctness under concurrent access (unique constraints still enforced)
- Can be optimized later if needed (batched upserts, temp tables, etc.)

## Implementation Details

### TextField to CharField Conversions

**Issue:** MS SQL Server cannot create unique indexes or unique constraints on `nvarchar(max)` (TEXT) columns.

**Solution:** 
1. Keep model files as `TextField(unique=True, db_index=True)` - no changes to models
2. Generate MS SQL migrations from models (will show TextField)
3. **Manually edit** MS SQL migrations to replace TextField → CharField(max_length=450)
4. Document the manual edits in migration file comments

**Why this approach:**
- Avoids creating new PostgreSQL migrations (PostgreSQL uses TEXT, works fine)
- MS SQL migrations work correctly (VARCHAR with indexes)
- Model definition doesn't match MS SQL schema, but Django doesn't re-check after initial migration
- Can be aligned in the future if fields are modified for other reasons

**Why 450 chars?**
- MS SQL Server index key size limit: 900 bytes
- nvarchar encoding: 2 bytes per character
- 450 chars × 2 bytes = 900 bytes (maximum safe size)

**Affected fields (from PoC analysis):**

**ansible_base/rbac/models/role.py:**
- `RoleDefinition.name` - TextField → CharField(max_length=450, unique=True, db_index=True)
- `ObjectRole.object_id` - TextField → CharField(max_length=450, db_index=True)
- `ObjectRole.parent_reference` - TextField → CharField(max_length=450, db_index=True)
- `RoleEvaluation.codename` - TextField → CharField(max_length=100)
- `RoleEvaluationUuid.codename` - TextField → CharField(max_length=100)

**ansible_base/resource_registry/models/resource.py:**
- `Resource.object_id` - TextField → CharField(max_length=450, db_index=True)

**Manual edit example:**
```python
# In ansible_base/rbac/mssql_migrations/0001_initial.py
# MANUAL EDIT: Changed from TextField to CharField(max_length=450)
# for MS SQL Server index compatibility. PostgreSQL migrations
# remain unchanged and use TextField.
migrations.AlterField(
    model_name='roledefinition',
    name='name',
    field=models.CharField(
        max_length=450, 
        db_index=True, 
        unique=True, 
        help_text='The name of this role.'
    ),
),
```

### Migration Generation Process

1. **Setup MS SQL Server test database:**
   ```bash
   make mssql
   DB_BACKEND=mssql python manage.py migrate  # Apply any existing migrations first
   ```

2. **Generate squashed migrations for each app:**
   ```bash
   # For each of the 10 apps:
   DB_BACKEND=mssql python manage.py makemigrations ansible_base.rbac --name initial
   # Move to mssql_migrations/ directory
   # Manually edit TextField → CharField where needed
   # Test migration applies cleanly
   ```

3. **Verify migration selection:**
   ```bash
   # Test PostgreSQL still works
   make postgres
   python manage.py migrate  # Should use migrations/
   
   # Test MS SQL Server uses new migrations
   make mssql
   DB_BACKEND=mssql python manage.py migrate  # Should use mssql_migrations/
   ```

4. **Document manual edits:**
   - Add comments in migration files noting manual edits
   - Document in `docs/mssql-support.md`
   - Note in this spec

## Development Environment

### Docker Compose - MS SQL Server

**File: `docker-compose.mssql.yml`**
```yaml
---
# MS SQL Server 2025 Developer Edition for django-ansible-base development
# 
# WARNING: This configuration is for DEVELOPMENT AND TESTING ONLY.
# Production deployments must use proper TLS/SSL certificate validation per ANSTRAT-1887 R3.
# The TrustServerCertificate setting in test_app/mssqlsettings.py bypasses certificate
# verification and is NOT suitable for production use.
services:
  mssql:
    image: mcr.microsoft.com/mssql/server:2025-latest
    container_name: dab_mssql
    environment:
      ACCEPT_EULA: "Y"
      MSSQL_SA_PASSWORD: "YourStrong!Passw0rd"
      MSSQL_PID: "Developer"
    ports:
      - "55433:1433"
    healthcheck:
      test: /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "YourStrong!Passw0rd" -C -Q "SELECT 1" -b -o /dev/null
      interval: 10s
      timeout: 3s
      retries: 10
      start_period: 10s
    volumes:
      # Optional: persist data between restarts
      - dab_mssql_data:/var/opt/mssql

volumes:
  dab_mssql_data:
```

**Makefile additions:**
```makefile
## Starts an MS SQL Server container in the background if one is not running
mssql:
	docker start dab_mssql || $(DOCKER_COMPOSE) -f docker-compose.mssql.yml up -d mssql --quiet-pull

## Stops the MS SQL Server container started with 'make mssql'
stop-mssql:
	echo "Killing dab_mssql container"
	$(DOCKER_COMPOSE) -f docker-compose.mssql.yml rm -fsv mssql
```

### Test App MS SQL Configuration

**File: `test_app/mssqlsettings.py`**
```python
"""
MS SQL Server settings for test_app.
Loaded when DB_BACKEND=mssql environment variable is set.

WARNING: This configuration is for DEVELOPMENT AND TESTING ONLY.
TrustServerCertificate=yes bypasses certificate verification and is NOT
suitable for production use. Production deployments must use proper
TLS/SSL certificate validation per ANSTRAT-1887 R3.

Usage:
    DB_BACKEND=mssql python manage.py runserver
    DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh
"""
import os

# Inherit from defaults
from test_app.defaults import *  # noqa: F403, F401

# Override database configuration for MS SQL Server
DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", 55433),
        "USER": os.getenv("DB_USER", "sa"),
        "PASSWORD": os.getenv("DB_PASSWORD", "YourStrong!Passw0rd"),
        "NAME": os.getenv("DB_NAME", "dab_db"),
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            # WARNING: TrustServerCertificate=yes is for DEVELOPMENT ONLY
            # Production must use proper certificate validation
            "extra_params": "TrustServerCertificate=yes",
        },
    }
}

# MS SQL Server doesn't need the PG_NOTIFY_DATABASES setting
# Consumer apps should use get_sql_server_notify_params() instead
```

**Modified: `test_app/scripts/bootstrap.sh`**

Add DB_BACKEND detection at the beginning:
```bash
#!/usr/bin/env bash

set -e

# Detect database backend from environment (default: postgres)
DB_BACKEND=${DB_BACKEND:-postgres}

# Set appropriate variables based on backend
if [[ "$DB_BACKEND" == "mssql" ]]; then
    CONTAINER_NAME="dab_mssql"
    MAKE_START_TARGET="mssql"
    MAKE_STOP_TARGET="stop-mssql"
    export DJANGO_SETTINGS_MODULE="test_app.mssqlsettings"
else
    CONTAINER_NAME="dab_postgres"
    MAKE_START_TARGET="postgres"
    MAKE_STOP_TARGET="stop-postgres"
    export DJANGO_SETTINGS_MODULE="test_app.settings"
fi

# Always make sure we kill the database when we exit
function cleanup {
    echo "***"
    echo "This will delete all data in the test_app database (container: $CONTAINER_NAME)"
    echo "Press:"
    echo " - Ctrl-C to cancel and leave the database running"
    echo " - Enter to continue shutdown and delete the database"
    echo "***"
    read
    make $MAKE_STOP_TARGET
}

trap cleanup EXIT

docker_running=$(docker ps -aq -f name=$CONTAINER_NAME)
migrate_needed=1

if [[ -z "${docker_running// /}" ]]
then
    echo "Creating new $DB_BACKEND container: $CONTAINER_NAME"
    make $MAKE_START_TARGET
else
    echo "$CONTAINER_NAME container is already running, will use that container"
    set +e
    python manage.py migrate --check; migrate_needed=$?
    set -e
fi

# Rest of script continues as-is...
```

### Dependencies

**pyproject.toml:**
```toml
dependencies = [
    ...existing dependencies...
    "mssql-django>=1.4",
    "pyodbc>=5.0.0",
]
```

**requirements/requirements.txt:**
```
# Existing requirements...

# MS SQL Server support
mssql-django>=1.4
pyodbc>=5.0.0
```

**Note:** System-level dependency for ODBC driver (not in Python requirements):
- Developer machines: `ODBC Driver 18 for SQL Server` must be installed
- Container images: Already included in `mcr.microsoft.com/mssql/server:2025-latest`
- Production deployments: Consumer apps document driver installation

## Testing

### Unit Tests

**New: `test_app/tests/lib/test_migration_modules.py`**
```python
"""Tests for selecting the project migration set from the default database backend."""

import json
import os
import subprocess
import sys

import pytest


def _load_migration_modules_for_engine(engine):
    """Load Django settings with specified engine and return MIGRATION_MODULES."""
    env = os.environ.copy()
    env.update({
        "DJANGO_SETTINGS_MODULE": "test_app.settings",
        "DB_HOST": "127.0.0.1",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
        "DB_NAME": "test",
    })
    
    # Set database engine
    if engine == "mssql":
        env["DB_BACKEND"] = "mssql"
        env["DJANGO_SETTINGS_MODULE"] = "test_app.mssqlsettings"
    
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; import django; django.setup(); from django.conf import settings; "
            "print(json.dumps(getattr(settings, 'MIGRATION_MODULES', {}), sort_keys=True))",
        ],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.unit
def test_mssql_database_selects_mssql_migrations():
    """MS SQL Server engine uses mssql_migrations for all DAB apps."""
    modules = _load_migration_modules_for_engine("mssql")
    
    expected = {
        "ansible_base.rbac": "ansible_base.rbac.mssql_migrations",
        "ansible_base.resource_registry": "ansible_base.resource_registry.mssql_migrations",
        "ansible_base.rest_filters": "ansible_base.rest_filters.mssql_migrations",
        "ansible_base.rest_pagination": "ansible_base.rest_pagination.mssql_migrations",
        "ansible_base.activitystream": "ansible_base.activitystream.mssql_migrations",
        "ansible_base.api_documentation": "ansible_base.api_documentation.mssql_migrations",
        "ansible_base.authentication": "ansible_base.authentication.mssql_migrations",
        "ansible_base.feature_flags": "ansible_base.feature_flags.mssql_migrations",
        "ansible_base.jwt_consumer": "ansible_base.jwt_consumer.mssql_migrations",
        "ansible_base.oauth2_provider": "ansible_base.oauth2_provider.mssql_migrations",
    }
    
    assert modules == expected


@pytest.mark.unit
def test_postgresql_database_uses_default_migrations():
    """PostgreSQL engine uses default migrations (no MIGRATION_MODULES override)."""
    modules = _load_migration_modules_for_engine("postgresql")
    
    # Should be empty dict or not include DAB apps
    # (default behavior is to use migrations/ directory)
    for app in ["rbac", "resource_registry", "authentication"]:
        assert f"ansible_base.{app}" not in modules
```

**Extended: `test_app/tests/lib/utils/test_db.py`**

Add MS SQL Server test cases to existing advisory lock tests:
```python
@pytest.mark.skipif(connection.vendor != "microsoft", reason="MS SQL Server only")
def test_advisory_lock_mssql():
    """Test MS SQL Server advisory lock using sp_getapplock."""
    with advisory_lock('test_lock_mssql') as acquired:
        assert acquired is True
        # Lock is held, verify we can't acquire again without shared mode
        # (test in separate connection/thread)


@pytest.mark.skipif(connection.vendor != "microsoft", reason="MS SQL Server only")
def test_advisory_lock_mssql_shared():
    """Test MS SQL Server shared locks."""
    with advisory_lock('test_shared_mssql', shared=True) as acquired1:
        assert acquired1 is True
        # Should be able to acquire shared lock from another connection
        with advisory_lock('test_shared_mssql', shared=True) as acquired2:
            assert acquired2 is True


@pytest.mark.skipif(connection.vendor != "microsoft", reason="MS SQL Server only")
def test_get_sql_server_notify_params():
    """Test SQL Server notify params extraction."""
    params = get_sql_server_notify_params()
    assert 'server' in params
    assert 'database' in params
    assert params['database'] == settings.DATABASES['default']['NAME']
```

### Integration Tests

**Existing test suite:**
- Run all existing DAB tests against MS SQL Server
- Focus areas:
  - RBAC tests (migrations, caching, advisory locks)
  - Resource registry tests (object_id handling)
  - Authentication tests (authenticator models)
  - Activity stream tests (JSONField usage)

**CI/CD additions (future work):**
```yaml
# .github/workflows/test.yml (example)
strategy:
  matrix:
    database:
      - postgres
      - mssql
    python-version: [3.11, 3.12]

steps:
  - name: Start database
    run: |
      if [ "${{ matrix.database }}" == "mssql" ]; then
        make mssql
      else
        make postgres
      fi
  
  - name: Run tests
    env:
      DB_BACKEND: ${{ matrix.database }}
    run: |
      pytest
```

### Manual Testing Checklist

Developer verification before marking complete:

- [ ] MS SQL Server container starts: `make mssql`
- [ ] Bootstrap script works: `DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh`
- [ ] Migrations apply cleanly: `python manage.py migrate`
- [ ] Test app starts: `python manage.py runserver`
- [ ] Django admin accessible at `/admin/`
- [ ] Can create User, Team, Organization through admin
- [ ] Can create RoleDefinition, ObjectRole through admin
- [ ] RBAC permissions evaluated correctly
- [ ] No PostgreSQL-specific errors in logs
- [ ] Advisory locks work (check during concurrent access)
- [ ] Container stops cleanly: `make stop-mssql`

**PostgreSQL regression testing:**
- [ ] All above tests also pass with PostgreSQL (default)
- [ ] No changes to existing PostgreSQL migrations
- [ ] Existing PostgreSQL deployments unaffected

## Documentation

### Files to Create/Update

**New: `docs/mssql-support.md`**
```markdown
# MS SQL Server Support

## Overview

Django-ansible-base supports both PostgreSQL and MS SQL Server 2019+ as database backends. The migration system automatically selects the appropriate migrations based on your configured database engine.

## Supported Databases

- **PostgreSQL** (default, production-tested)
  - Uses `ansible_base/<app>/migrations/`
  - Full feature support
  
- **MS SQL Server 2019+**
  - Uses `ansible_base/<app>/mssql_migrations/`
  - Feature parity with PostgreSQL
  - Targets MS SQL Server 2019 and newer

## How It Works

### Automatic Migration Selection

When Django starts, django-ansible-base inspects `settings.DATABASES['default']['ENGINE']`:

- `django.db.backends.postgresql` → uses `migrations/` (PostgreSQL)
- `mssql` → uses `mssql_migrations/` (MS SQL Server)

No additional configuration needed - just set your database engine.

### Architecture

Consumer applications (controller, gateway, EDA, metrics, lightspeed) configure their database engine in settings. Django-ansible-base automatically loads the correct migration set.

```python
# Consumer app settings
DATABASES = {
    'default': {
        'ENGINE': 'mssql',  # or 'django.db.backends.postgresql'
        # ... other settings
    }
}

# DAB automatically sets:
MIGRATION_MODULES = {
    'ansible_base.rbac': 'ansible_base.rbac.mssql_migrations',  # for mssql
    # or uses default migrations/ for postgresql
}
```

## Important Notes

### Migration Differences

MS SQL Server migrations were **manually edited** after generation to work around database limitations:

1. **TextField → CharField conversions:**
   - Fields: `RoleDefinition.name`, `ObjectRole.object_id`, `Resource.object_id`, etc.
   - Reason: MS SQL Server cannot index `nvarchar(max)` with unique constraints
   - Changed to: `CharField(max_length=450)` in MS SQL migrations only
   - **Do NOT run `makemigrations` against MS SQL Server** - it will try to regenerate these

2. **Model definitions remain as TextField:**
   - Django models still use `TextField` (matches PostgreSQL)
   - MS SQL migrations differ from model definitions
   - This is intentional and documented
   - Can be aligned in future if fields are modified for other reasons

### Database-Specific Features

**Advisory Locks:**
- PostgreSQL: `pg_advisory_lock()` SQL function
- MS SQL Server: `sp_getapplock` stored procedure
- Same API in DAB, different implementation

**Bulk Operations:**
- PostgreSQL: `bulk_create(ignore_conflicts=True)` - single query
- MS SQL Server: Falls back to `get_or_create` per object - multiple queries
- Functionally equivalent, MS SQL path is slower but acceptable

**Dispatcher/NOTIFY:**
- PostgreSQL: Use `get_pg_notify_params()` for pg_notify broker
- MS SQL Server: Use `get_sql_server_notify_params()` for SQL Server broker
- Consumer apps check `connection.vendor` and call appropriate function

## Development Setup

### Prerequisites

**System dependencies:**
- ODBC Driver 18 for SQL Server (or newer)
  - Linux: Install `msodbcsql18` package
  - macOS: Install via Homebrew
  - Windows: Download from Microsoft

**Python dependencies:**
Already included in django-ansible-base requirements:
- `mssql-django>=1.4`
- `pyodbc>=5.0.0`

### Local MS SQL Server Development

**1. Start MS SQL Server container:**
```bash
make mssql
```

This starts a SQL Server 2025 Developer Edition container:
- Container name: `dab_mssql`
- Port: 55433 (mapped to internal 1433)
- SA password: `YourStrong!Passw0rd`
- Database: Created on first migration

**2. Run test_app with MS SQL Server:**
```bash
DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh
```

This script:
- Starts MS SQL container if not running
- Waits for database to be ready
- Runs migrations (uses mssql_migrations/)
- Creates admin user
- Initializes authenticators
- Starts test_app server

**3. Manual setup (alternative):**
```bash
make mssql
DB_BACKEND=mssql python manage.py migrate
DB_BACKEND=mssql python manage.py createsuperuser
DB_BACKEND=mssql python manage.py authenticators --initialize
DB_BACKEND=mssql python manage.py runserver
```

**4. Stop MS SQL Server:**
```bash
make stop-mssql
```

### Running Tests with MS SQL Server

```bash
# Start MS SQL container
make mssql

# Run tests with MS SQL backend
DB_BACKEND=mssql pytest

# Or specific test module
DB_BACKEND=mssql pytest test_app/tests/rbac/
```

## Production Deployment

### Database Configuration

**MS SQL Server settings example:**
```python
DATABASES = {
    'default': {
        'ENGINE': 'mssql',
        'HOST': 'sqlserver.example.com',
        'PORT': 1433,
        'USER': 'dab_user',
        'PASSWORD': os.environ['DB_PASSWORD'],
        'NAME': 'dab_production',
        'OPTIONS': {
            'driver': 'ODBC Driver 18 for SQL Server',
            'extra_params': 'Encrypt=yes;TrustServerCertificate=no',
        },
    }
}
```

### Migrations

**Initial deployment:**
```bash
python manage.py migrate
```

Migration selection happens automatically based on `ENGINE=mssql`.

**Future updates:**
When updating django-ansible-base version:
```bash
python manage.py migrate
```

New migrations in `mssql_migrations/` are applied automatically.

### Dispatcher Configuration

For AWX/controller using dispatcherd:

```python
from django.db import connection
from ansible_base.lib.utils.db import get_pg_notify_params, get_sql_server_notify_params

def get_dispatcherd_config():
    if connection.vendor == "postgresql":
        return {
            "brokers": {
                "pg_notify": {
                    "config": get_pg_notify_params(),
                    "sync_connection_factory": "ansible_base.lib.utils.db.psycopg_connection_from_django",
                }
            }
        }
    elif connection.vendor == "microsoft":
        return {
            "brokers": {
                "sql_server": {
                    "config": get_sql_server_notify_params(),
                }
            }
        }
```

## Troubleshooting

### Migration Issues

**Problem:** Migration fails with "cannot index nvarchar(max)"

**Solution:** Verify you're using the MS SQL migrations, not PostgreSQL migrations:
```python
# Check in Django shell
from django.conf import settings
print(settings.MIGRATION_MODULES)

# Should show mssql_migrations for all DAB apps
```

**Problem:** `makemigrations` detects changes on MS SQL Server

**Solution:** Don't run `makemigrations` against MS SQL Server. The model definitions intentionally differ from MS SQL migrations. If you need new migrations, create them for PostgreSQL first, then manually port to MS SQL.

### Connection Issues

**Problem:** "Can't open lib 'ODBC Driver 18 for SQL Server'"

**Solution:** Install ODBC driver:
```bash
# Debian/Ubuntu
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql18
```

**Problem:** "Login failed for user 'sa'"

**Solution:** Check container is running and password is correct:
```bash
docker logs dab_mssql
# Look for "SQL Server is now ready for client connections"
```

### Performance Issues

**Problem:** RBAC operations slow on MS SQL Server

**Expected:** Some operations use `get_or_create` fallback instead of bulk operations. This is expected and acceptable for MS SQL deployments.

**Mitigation:** If needed, MS SQL Server performance can be optimized later with:
- Batched upserts
- Temporary tables
- MERGE statements
- But current implementation is correct and acceptable

## FAQ

**Q: Can I mix PostgreSQL and MS SQL Server?**

A: No. The `default` database engine determines which migrations are used. All instances of a deployment must use the same database backend.

**Q: Can I migrate from PostgreSQL to MS SQL Server?**

A: Not directly. You would need to:
1. Export data from PostgreSQL
2. Set up fresh MS SQL Server database
3. Run MS SQL migrations
4. Import data (with transformations as needed)

This is not a supported or tested workflow.

**Q: Why not use database-agnostic migrations?**

A: Some database limitations (like MS SQL's indexed TEXT restriction) require different schema definitions. Separate migration sets are cleaner and safer than conditional migration logic.

**Q: Will new features work on both databases?**

A: Yes. New DAB features must support both PostgreSQL and MS SQL Server. New migrations will be added to both `migrations/` and `mssql_migrations/`.

**Q: What about other databases (MySQL, Oracle)?**

A: Not currently supported. Only PostgreSQL and MS SQL Server are tested and supported.
```

**Modified: `test_app/README.md`**

Add section after "Setting up an environment":
```markdown
## Using MS SQL Server

django-ansible-base supports MS SQL Server 2019+ in addition to PostgreSQL. To run test_app with MS SQL Server:

### Quick Start

```bash
DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh
```

This automatically:
- Starts MS SQL Server container (Developer Edition)
- Waits for database to be ready
- Runs migrations using `mssql_migrations/`
- Creates admin user
- Initializes authenticators
- Starts test_app server

### Manual Setup

If you prefer manual steps:

**1. Start MS SQL Server container:**
```bash
make mssql
```

**2. Run migrations:**
```bash
DB_BACKEND=mssql python manage.py migrate
```

**3. Create admin user:**
```bash
DB_BACKEND=mssql python manage.py createsuperuser
```

**4. Initialize authenticators:**
```bash
DB_BACKEND=mssql python manage.py authenticators --initialize
```

**5. Start test_app:**
```bash
DB_BACKEND=mssql python manage.py runserver
```

**6. Stop MS SQL Server when done:**
```bash
make stop-mssql
```

### Connection Details

- **Host:** localhost
- **Port:** 55433 (external) → 1433 (internal)
- **User:** sa
- **Password:** YourStrong!Passw0rd
- **Database:** dab_db (created on first migration)

### Running Tests

```bash
make mssql
DB_BACKEND=mssql pytest
```

See [docs/mssql-support.md](../docs/mssql-support.md) for detailed MS SQL Server documentation.
```

**Modified: `README.md` (root)**

Add to the top-level README after the "What is it?" section:
```markdown
## Database Support

django-ansible-base supports:
- **PostgreSQL** (default, production-tested)
- **MS SQL Server 2019+** (for AAP components)

Migration selection is automatic based on your configured database engine. See [docs/mssql-support.md](docs/mssql-support.md) for MS SQL Server setup and usage.
```

## Implementation Plan

### Phase 1: Core Infrastructure (Foundation)

**Tasks:**
1. Add mssql-django and pyodbc dependencies
   - Update `pyproject.toml`
   - Update `requirements/requirements.txt`
   - Test installation in clean venv

2. Create migration selection AppConfig
   - File: `ansible_base/lib/apps.py`
   - Implement `AnsibleBaseConfig` with `ready()` method
   - ENGINE_MIGRATION_MAP and MIGRATION_MODULES logic
   - Wire into Django app registry

3. Add MS SQL Server advisory lock implementation
   - File: `ansible_base/lib/utils/db.py`
   - Implement `_convert_lock_id_to_resource_name()`
   - Add MS SQL Server branch to `advisory_lock()` using sp_getapplock
   - Handle timeout, shared/exclusive modes
   - Test with PostgreSQL (no regression), SQLite (existing), MS SQL (new)

4. Add `get_sql_server_notify_params()` helper
   - File: `ansible_base/lib/utils/db.py`
   - Parallel to `get_pg_notify_params()`
   - Support SQL_SERVER_NOTIFY_DATABASES override setting
   - Return pyodbc-compatible connection dict

**Estimated effort:** 2-3 days

**Dependencies:** None

**Validation:**
- [ ] Dependencies install cleanly
- [ ] AppConfig loads and sets MIGRATION_MODULES correctly
- [ ] Advisory lock tests pass (add MS SQL test cases)
- [ ] `get_sql_server_notify_params()` unit tests pass

---

### Phase 2: Docker Environment (Development Setup)

**Tasks:**
1. Create `docker-compose.mssql.yml`
   - SQL Server 2025 Developer Edition
   - Container name: dab_mssql
   - Port mapping: 55433:1433
   - Healthcheck with sqlcmd
   - Volume for persistence (optional)

2. Add Makefile targets
   - `make mssql` - start container
   - `make stop-mssql` - stop container
   - Test both targets

3. Create `test_app/mssqlsettings.py`
   - Inherit from test_app.defaults
   - Override DATABASES with MS SQL config
   - Document environment variables
   - Test settings load correctly

4. Modify `test_app/scripts/bootstrap.sh`
   - Detect DB_BACKEND environment variable
   - Support both postgres and mssql paths
   - Container name selection
   - Make target selection
   - Settings module selection
   - Test both backends

**Estimated effort:** 1-2 days

**Dependencies:** Phase 1 complete

**Validation:**
- [ ] `make mssql` starts container successfully
- [ ] Container passes healthcheck
- [ ] `DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh` works end-to-end
- [ ] Can connect to MS SQL Server from Django shell
- [ ] `make stop-mssql` cleans up container

---

### Phase 3: MS SQL Migrations - Group 1 (Simple Apps)

Generate and test MS SQL migrations for apps with simple schemas (no complex indexes or TextField issues):

**Tasks:**
1. `rest_filters` app
   - Create `ansible_base/rest_filters/mssql_migrations/`
   - Generate squashed migration against MS SQL
   - Test migration applies cleanly
   - Verify no manual edits needed

2. `rest_pagination` app
   - Create `ansible_base/rest_pagination/mssql_migrations/`
   - Generate squashed migration
   - Test migration
   - Verify no manual edits needed

3. `api_documentation` app
   - Create `ansible_base/api_documentation/mssql_migrations/`
   - Generate squashed migration (likely empty, no models)
   - Test migration

4. `feature_flags` app
   - Create `ansible_base/feature_flags/mssql_migrations/`
   - Generate squashed migration
   - Test migration
   - Verify no manual edits needed

5. `jwt_consumer` app
   - Create `ansible_base/jwt_consumer/mssql_migrations/`
   - Generate squashed migration
   - Test migration
   - Verify no manual edits needed

**Estimated effort:** 2-3 days

**Dependencies:** Phase 2 complete (need MS SQL container running)

**Validation:**
- [ ] Each app's mssql_migrations/ directory created
- [ ] Migrations apply cleanly on fresh MS SQL database
- [ ] No errors in Django checks
- [ ] Test app loads successfully

---

### Phase 4: MS SQL Migrations - Group 2 (Complex Apps)

Generate MS SQL migrations for apps requiring manual TextField → CharField edits:

**Tasks:**
1. `rbac` app (**Most complex**)
   - Create `ansible_base/rbac/mssql_migrations/`
   - Generate squashed migration against MS SQL
   - **Manually edit** migration:
     - `RoleDefinition.name`: TextField → CharField(max_length=450)
     - `ObjectRole.object_id`: TextField → CharField(max_length=450)
     - `ObjectRole.parent_reference`: TextField → CharField(max_length=450)
     - `RoleEvaluation.codename`: TextField → CharField(max_length=100)
     - `RoleEvaluationUuid.codename`: TextField → CharField(max_length=100)
   - Add comments documenting manual edits
   - Test migration applies cleanly
   - Verify unique constraints work
   - Test RBAC functionality (create roles, assignments)

2. `resource_registry` app
   - Create `ansible_base/resource_registry/mssql_migrations/`
   - Generate squashed migration
   - **Manually edit:**
     - `Resource.object_id`: TextField → CharField(max_length=450)
   - Add comments documenting manual edits
   - Test migration
   - Test resource registration

3. `authentication` app
   - Create `ansible_base/authentication/mssql_migrations/`
   - Generate squashed migration
   - Check for TextField issues (authenticator configuration JSONField should be fine)
   - Manually edit if needed
   - Test migration
   - Test authenticator creation

4. `activitystream` app
   - Create `ansible_base/activitystream/mssql_migrations/`
   - Generate squashed migration
   - Verify JSONField works on MS SQL (should be fine)
   - Test migration
   - Test activity stream entry creation

5. `oauth2_provider` app
   - Create `ansible_base/oauth2_provider/mssql_migrations/`
   - Generate squashed migration
   - Check for any TextField issues
   - Manually edit if needed
   - Test migration
   - Test OAuth2 application creation

**Estimated effort:** 4-5 days

**Dependencies:** Phase 3 complete

**Validation:**
- [ ] All mssql_migrations/ directories created
- [ ] Manual edits documented in migration files
- [ ] All migrations apply cleanly on fresh MS SQL database
- [ ] Can create objects through Django admin for each app
- [ ] No database errors in logs

---

### Phase 5: Bulk Create Optimizations

Update RBAC caching and pipeline code to handle MS SQL bulk create limitations:

**Tasks:**
1. Implement `_bulk_create_ignore_conflicts()` helper
   - File: `ansible_base/rbac/pipeline.py` (or utils)
   - Check `connection.features.supports_ignore_conflicts`
   - PostgreSQL path: `bulk_create(ignore_conflicts=True)`
   - MS SQL path: loop with `get_or_create()`

2. Update `ansible_base/rbac/caching.py`
   - Replace `_bulk_create_evaluations()` implementation
   - Use new helper function
   - Test on PostgreSQL (no regression)
   - Test on MS SQL (functional correctness)

3. Update `ansible_base/rbac/pipeline.py`
   - `_ensure_object_roles()` - ObjectRole creation
   - `_create_assignments()` - RoleUserAssignment, RoleTeamAssignment
   - Replace `bulk_create(ignore_conflicts=True)` calls
   - Use new helper with appropriate unique_fields

4. Performance testing
   - Measure MS SQL performance (expected slower, but acceptable)
   - Verify concurrent access correctness
   - Document performance characteristics

**Estimated effort:** 2-3 days

**Dependencies:** Phase 4 complete (need migrations in place)

**Validation:**
- [ ] RBAC caching works on MS SQL
- [ ] Assignment pipeline works on MS SQL
- [ ] No regression on PostgreSQL
- [ ] Concurrent access tests pass
- [ ] Performance acceptable (document if slower)

---

### Phase 6: Testing Infrastructure

Add MS SQL test support and comprehensive test coverage:

**Tasks:**
1. Create `test_app/tests/lib/test_migration_modules.py`
   - Test MS SQL engine selects mssql_migrations
   - Test PostgreSQL engine uses default migrations
   - Follow metrics-service pattern

2. Extend `test_app/tests/lib/utils/test_db.py`
   - Add MS SQL advisory lock tests
   - Test `get_sql_server_notify_params()`
   - Skip tests appropriately based on `connection.vendor`

3. Run full test suite against MS SQL
   - Identify any failing tests
   - Fix database-specific issues
   - Document any known limitations

4. Add test documentation
   - How to run tests with MS SQL
   - CI/CD integration guidance (future work)
   - Test matrix strategy

**Estimated effort:** 3-4 days

**Dependencies:** Phase 5 complete

**Validation:**
- [ ] Migration selection tests pass
- [ ] Advisory lock tests pass on MS SQL
- [ ] Full test suite passes on PostgreSQL (no regression)
- [ ] Full test suite passes on MS SQL Server
- [ ] Test coverage maintained

---

### Phase 7: Documentation

Create comprehensive documentation for MS SQL Server support:

**Tasks:**
1. Create `docs/mssql-support.md`
   - Overview and architecture
   - Migration differences and manual edits
   - Development setup
   - Production deployment
   - Troubleshooting
   - FAQ

2. Update `test_app/README.md`
   - Add "Using MS SQL Server" section
   - Document bootstrap.sh with DB_BACKEND
   - Connection details
   - Running tests

3. Update root `README.md`
   - Add database support section
   - Link to mssql-support.md

4. Document in this spec
   - Implementation details
   - Known limitations
   - Future work

**Estimated effort:** 2 days

**Dependencies:** Phase 6 complete (need actual experience to document)

**Validation:**
- [ ] Documentation accurate and complete
- [ ] New developer can follow docs to set up MS SQL
- [ ] Troubleshooting section covers common issues
- [ ] Links work, examples tested

---

### Phase 8: Final Integration and Validation

End-to-end testing and cleanup:

**Tasks:**
1. Fresh environment testing
   - Clone fresh repo
   - Follow documentation exactly
   - Both PostgreSQL and MS SQL paths
   - Document any issues found

2. Migration testing
   - Fresh PostgreSQL database → migrate
   - Fresh MS SQL database → migrate
   - Verify both work independently

3. Consumer app integration testing
   - Test django-ansible-base changes in controller (if available)
   - Test in gateway (if available)
   - Verify migrations load correctly in consumer context

4. Performance validation
   - RBAC operations on both databases
   - Document any significant performance differences
   - Ensure MS SQL performance acceptable

5. Final documentation review
   - Verify all docs accurate
   - Update any outdated information
   - Add any lessons learned

**Estimated effort:** 2-3 days

**Dependencies:** Phase 7 complete

**Validation:**
- [ ] Fresh install works for PostgreSQL
- [ ] Fresh install works for MS SQL
- [ ] All documentation tested and accurate
- [ ] Performance documented
- [ ] Ready for PR/review

---

## Total Estimated Effort

- Phase 1: 2-3 days
- Phase 2: 1-2 days
- Phase 3: 2-3 days
- Phase 4: 4-5 days
- Phase 5: 2-3 days
- Phase 6: 3-4 days
- Phase 7: 2 days
- Phase 8: 2-3 days

**Total: 18-25 days** (approximately 4-5 weeks for a single developer)

Can be parallelized:
- Phase 3 and 4 can be split across multiple developers (per-app work)
- Phase 5 can start once Phase 4 RBAC migrations are done
- Documentation (Phase 7) can be done in parallel with testing (Phase 6)

**Parallelized: ~3-4 weeks** with 2-3 developers

## Risks and Mitigations

### Risk: MS SQL Migrations Drift from Models

**Impact:** Medium  
**Likelihood:** Medium

**Description:** MS SQL migrations have TextField → CharField manual edits. If someone runs `makemigrations` against MS SQL, Django will detect differences and try to "fix" them.

**Mitigation:**
- Clear documentation: "DO NOT run makemigrations against MS SQL"
- Add comments in migration files warning about manual edits
- Consider pre-commit hook to prevent accidental generation
- Add CI check to verify mssql_migrations haven't been auto-regenerated

### Risk: Performance Degradation on MS SQL

**Impact:** Medium  
**Likelihood:** Low

**Description:** Bulk create fallback using `get_or_create` loops is slower than PostgreSQL's single-query bulk insert.

**Mitigation:**
- Document performance characteristics
- Only affects RBAC caching/assignment operations (not critical path)
- Can optimize later if needed (batched upserts, MERGE statements)
- Test and document actual performance impact

### Risk: Missing PostgreSQL-Specific Features

**Impact:** High  
**Likelihood:** Low

**Description:** Additional PostgreSQL-specific code exists that wasn't identified in initial analysis.

**Mitigation:**
- Phase 6 runs full test suite against MS SQL
- Any failures will identify missing features
- Review all database queries in DAB codebase
- Search for PostgreSQL-specific functions/types

### Risk: Consumer App Integration Issues

**Impact:** High  
**Likelihood:** Medium

**Description:** Controller, gateway, EDA may have their own PostgreSQL-specific code that breaks with MS SQL DAB.

**Mitigation:**
- This spec only covers DAB changes
- Consumer apps need their own MS SQL migration work
- Document integration requirements for consumer apps
- Test in at least one consumer app (controller or gateway) before finalizing

### Risk: Docker/ODBC Driver Issues

**Impact:** Low  
**Likelihood:** Medium

**Description:** Developers may have trouble installing ODBC drivers or running MS SQL containers.

**Mitigation:**
- Comprehensive troubleshooting section in docs
- Test on multiple platforms (Linux, macOS)
- Docker compose handles SQL Server container complexity
- Document common ODBC driver installation issues

## Future Work

### Short-term (Next 6 months)

1. **CI/CD Integration**
   - Add MS SQL Server test matrix to GitHub Actions
   - Run full test suite against both databases in CI
   - Prevent regressions

2. **Consumer App Migration**
   - Apply same pattern to controller (AWX)
   - Apply to gateway (aap-gateway)
   - Apply to EDA (eda-server)
   - Apply to metrics-service (already done)
   - Apply to lightspeed

3. **Performance Optimization**
   - If MS SQL bulk operations prove slow, optimize:
     - Use MERGE statements instead of get_or_create loops
     - Batch operations with temporary tables
     - Add indexes specific to MS SQL workload

### Medium-term (6-12 months)

1. **Model Alignment**
   - When TextField fields are modified for other reasons, align model definitions
   - Create migrations for both databases simultaneously
   - Eventually models match both database schemas

2. **Advanced Features**
   - Full Service Broker integration (if needed)
   - Query optimization for MS SQL
   - MS SQL-specific performance monitoring

3. **Additional Database Support**
   - MySQL support (if customer demand exists)
   - Same pattern: `mysql_migrations/` directories

### Long-term (12+ months)

1. **Unified Migration Generation**
   - Tool to generate migrations for both databases simultaneously
   - Automatic TextField → CharField conversion for MS SQL
   - Reduce manual work for future migrations

2. **Cross-Database Testing**
   - Automated tests that run against all supported databases
   - Catch database-specific issues early
   - Prevent PostgreSQL-specific code from being added

## Glossary

- **AAP** - Ansible Automation Platform
- **DAB** - django-ansible-base (this project)
- **MS SQL** - Microsoft SQL Server
- **RBAC** - Role-Based Access Control
- **dispatcherd** - Background task dispatcher used by AWX/controller
- **pg_notify** - PostgreSQL LISTEN/NOTIFY asynchronous notification system
- **Service Broker** - MS SQL Server asynchronous message-based communication system
- **Advisory Lock** - Database-level lock for distributed coordination
- **squashed migration** - Single migration that combines multiple migrations
- **pyodbc** - Python ODBC database connectivity library
- **mssql-django** - Django database backend for MS SQL Server

## References

- **Metrics Service PR #477:** https://github.com/ansible/metrics-service/pull/477
  - Reference implementation of MS SQL support pattern
  - Shows migration selection in apps.py
  - Shows mssql_migrations/ structure
  
- **mssql-django:** https://github.com/microsoft/mssql-django
  - Official Microsoft Django backend for SQL Server
  - Documentation and limitations
  
- **Django Migration Documentation:** https://docs.djangoproject.com/en/stable/topics/migrations/
  - MIGRATION_MODULES setting
  - Squashing migrations
  
- **SQL Server Advisory Locks:** https://learn.microsoft.com/en-us/sql/relational-databases/system-stored-procedures/sp-getapplock-transact-sql
  - sp_getapplock / sp_releaseapplock documentation
  
- **JIRA Ticket:** AAP-96550 - MS SQL Server support for django-ansible-base

## Approval Sign-off

- [x] Design reviewed and approved by: bhavenst (2026-10-19)
- [ ] Implementation complete
- [ ] Testing complete
- [ ] Documentation complete
- [ ] Ready for production use
