# MS SQL Server Support - Implementation Status

**Date:** 2026-10-21  
**JIRA:** AAP-98732 (formerly ANSTRAT-1887)  
**Initiative:** [ANSTRAT-1887](https://redhat.atlassian.net/browse/ANSTRAT-1887) - MS SQL Server Database Support - Technology Preview  
**Design Spec:** [docs/superpowers/specs/2026-10-19-mssql-support-design.md](superpowers/specs/2026-10-19-mssql-support-design.md)

## Executive Summary

**Status:** Phase 1-2 Complete ✅ | Phase 3 In Progress (Approach 4: Custom SchemaEditor) ⏳

Core infrastructure for MS SQL Server 2019+ support is complete. Implementing **Approach 4** (Custom Database Backend with SchemaEditor) for TextField compatibility - the most elegant solution that requires zero migration file changes.

## Implementation Approach

### Selected: Approach 4 - Custom SchemaEditor with Dynamic Conversion

**Why this approach:**
- ✅ Zero migration file changes - existing migrations work as-is
- ✅ Single migration tree for both PostgreSQL and MS SQL
- ✅ Transparent conversion during schema compilation
- ✅ No ongoing maintenance burden of parallel migrations
- ✅ Database-specific backends: PostgreSQL gets TextField, MS SQL gets VARCHAR

**How it works:**
1. Custom database backend (`ansible_base.backends.mssql`) extends `mssql-django`
2. Custom `DatabaseSchemaEditor` intercepts `column_sql()` method
3. Detects TextField with `db_index=True`, `unique=True`, or in constraints
4. Dynamically converts to `CharField(max_length=X)` during migration execution
5. PostgreSQL uses standard backend → gets TextField (unchanged)
6. MS SQL uses custom backend → gets VARCHAR (automatic conversion)

**Intelligent max_length selection:**
- `codename` fields → 100 (Django permission standard)
- `object_id`, `parent_reference` → 450 (MS SQL index limit: 900 bytes / 2 bytes per nvarchar)
- `name` → 255 (common standard)
- `singleton_name`, `role_field` → 64 (AWX-specific)
- Default → 450 (safe for all indexed fields)

## Completed Work

### Phase 1: Core Infrastructure ✅

#### 1. Dependencies ✅
- Added `mssql-django>=1.4` and `pyodbc>=5.0.0` to requirements
- Compiled to `requirements_all.txt` (mssql-django==2.0.0, pyodbc==5.3.0)
- Includes transitive dependencies: azure-core, azure-identity, msal

#### 2. MS SQL Server Advisory Locks ✅
- Implemented `sp_getapplock`/`sp_releaseapplock` in `ansible_base/lib/utils/db.py`
- Lock ID to resource name conversion (supports int/str/tuple)
- Shared and exclusive lock modes
- Timeout and non-blocking support
- Preserves existing PostgreSQL and SQLite implementations

#### 3. SQL Server Notify Params Helper ✅
- Implemented `get_sql_server_notify_params()` in `ansible_base/lib/utils/db.py`
- Parallel to `get_pg_notify_params()` for PostgreSQL
- Supports `SQL_SERVER_NOTIFY_DATABASES` override setting
- Returns pyodbc-compatible connection dict for dispatcherd Service Broker

### Phase 2: Docker Environment ✅

#### 1. Docker Compose Configuration ✅
- Created `docker-compose.mssql.yml` with SQL Server 2025 Developer Edition
- Container: `dab_mssql`, Port: 55433→1433, SA password configured
- Healthcheck with sqlcmd
- Named volume for data persistence

#### 2. Makefile Targets ✅
- `make mssql` - Start MS SQL Server container
- `make stop-mssql` - Stop MS SQL Server container
- Improved logic to check container state before starting

#### 3. Test App MS SQL Settings ✅
- Created `test_app/mssqlsettings.py` using dynaconf
- **Updated to use custom backend:** `ENGINE='ansible_base.backends.mssql'`
- Proper DATABASES configuration for MS SQL
- ODBC Driver 18 for SQL Server
- TrustServerCertificate=yes marked as dev-only

#### 4. Bootstrap Script Updates ✅
- Modified `test_app/scripts/bootstrap.sh` to support `DB_BACKEND` env var
- Auto-selects postgres (default) or mssql backend
- Database-specific connection checking
- Increased wait time for SQL Server startup

#### 5. Database Setup ✅
- SQL Server 2025 (RTM-CU9-GDR) KB5126967 - 17.0.5015.4 running
- Database `dab_db` created
- Verified pyodbc connections successful
- Django connects successfully with MS SQL settings

### Phase 3: Custom Backend Implementation ⏳

#### 1. Package Structure ✅
```
ansible_base/backends/
├── __init__.py
└── mssql/
    ├── __init__.py
    ├── base.py              # DatabaseWrapper
    ├── schema.py            # DatabaseSchemaEditor (conversion logic)
    └── tests/
        ├── __init__.py
        └── test_schema_editor.py  # Unit tests
```

#### 2. Custom SchemaEditor ✅
- `ansible_base/backends/mssql/schema.py` (~220 lines)
- `DatabaseSchemaEditor.column_sql()` - interception point
- `_field_needs_conversion()` - detects TextField with constraints
- `_determine_max_length()` - intelligent max_length selection
- `_copy_field_attrs()` - preserves field attributes
- Comprehensive logging for debugging

#### 3. Custom DatabaseWrapper ✅
- `ansible_base/backends/mssql/base.py` (~30 lines)
- Extends `mssql.base.DatabaseWrapper`
- Links custom SchemaEditor to mssql-django backend

#### 4. Unit Tests ✅
- `test_field_needs_conversion()` - constraint detection logic
- `test_determine_max_length()` - max_length selection for different field names
- `test_copy_field_attrs()` - attribute preservation
- Run with: `pytest ansible_base/backends/mssql/tests/`

#### 5. Settings Configuration ✅
- Updated `test_app/mssqlsettings.py` to use `ENGINE='ansible_base.backends.mssql'`
- Custom backend activated for all MS SQL deployments

## Testing Plan

### Unit Tests (Current Phase)
- [x] Test `_field_needs_conversion()` logic
- [x] Test `_determine_max_length()` selection
- [x] Test `_copy_field_attrs()` preservation
- [ ] Run tests: `pytest ansible_base/backends/mssql/tests/`

### Integration Tests (Next Phase)
- [ ] Fresh PostgreSQL install: Run all migrations (should get TextField)
- [ ] Fresh MS SQL install: Run all migrations (should get VARCHAR)
- [ ] Introspect both databases and compare schemas
- [ ] Verify indexes created successfully on MS SQL
- [ ] Verify unique constraints work on MS SQL

### Specific Field Tests
- [ ] django-ansible-base: 6 TextField issues
  - `RoleDefinition.name` → VARCHAR(450)
  - `ObjectRole.object_id` → VARCHAR(450)
  - `ObjectRole.parent_reference` → VARCHAR(450)
  - `RoleEvaluation.codename` → VARCHAR(100)
  - `RoleEvaluationUUID.codename` → VARCHAR(100)
  - `Resource.object_id` → VARCHAR(450)

### Commands for Testing

```bash
# Start MS SQL Server
make mssql

# Test with PostgreSQL (standard backend - should get TextField)
./test_app/scripts/bootstrap.sh
python manage.py sqlmigrate dab_rbac 0001 | grep -i text

# Test with MS SQL (custom backend - should get VARCHAR)
DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh
DB_BACKEND=mssql python manage.py sqlmigrate dab_rbac 0001 | grep -i varchar

# Introspect actual database schema
DB_BACKEND=mssql python manage.py inspectdb | grep -A5 "class RoleDefinition"

# Run all migrations on both databases
./test_app/scripts/bootstrap.sh && python manage.py migrate
DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh && python manage.py migrate
```

## TextField Issues Addressed

Based on comprehensive codebase survey (AAP-98732):

### django-ansible-base (6 fields)
| Model | Field | Issue | Converted To |
|-------|-------|-------|--------------|
| RoleDefinition | name | unique=True, db_index=True | VARCHAR(450) |
| ObjectRole | object_id | UniqueConstraint, db_index=True | VARCHAR(450) |
| ObjectRole | parent_reference | db_index=True | VARCHAR(450) |
| RoleEvaluation | codename | UniqueConstraint, Index | VARCHAR(100) |
| RoleEvaluationUUID | codename | UniqueConstraint, Index | VARCHAR(100) |
| Resource | object_id | UniqueConstraint, db_index=True | VARCHAR(450) |

### Other Components (for future work)
- **eda-server:** 8 fields (1 base class + 7 concrete)
- **awx:** 2 fields  
- **jewel, metrics-service, dispatcherd, metrics-utility:** 0 fields (compatible)

## Next Steps

### Immediate (Week 1)
1. **Run unit tests:**
   ```bash
   pytest ansible_base/backends/mssql/tests/test_schema_editor.py -v
   ```

2. **Test migration execution:**
   ```bash
   # PostgreSQL
   ./test_app/scripts/bootstrap.sh
   python manage.py migrate --plan
   python manage.py migrate
   
   # MS SQL Server
   DB_BACKEND=mssql ./test_app/scripts/bootstrap.sh
   python manage.py migrate --plan
   python manage.py migrate
   ```

3. **Verify schema conversion:**
   ```bash
   # Check what SQL will be generated
   python manage.py sqlmigrate dab_rbac 0001 | less
   DB_BACKEND=mssql python manage.py sqlmigrate dab_rbac 0001 | less
   
   # Compare: PostgreSQL should have TEXT, MS SQL should have VARCHAR
   ```

4. **Introspect database schemas:**
   ```bash
   python manage.py inspectdb dab_rbac_roledefinition
   DB_BACKEND=mssql python manage.py inspectdb dab_rbac_roledefinition
   ```

### Short-term (Weeks 2-3)
1. Run full test suite on both databases
2. Performance testing on MS SQL
3. Integration testing with full AAP stack
4. Documentation updates

### Known Limitations

1. **Dev-only TLS config:** `TrustServerCertificate=yes` bypasses certificate validation
   - **Production must use proper TLS/SSL** per ANSTRAT-1887 R3
   - Need proper certificates and certificate validation

2. **Protobuf conflict:** `ansible_base.observability` disabled in test_app
   - Not related to MS SQL support
   - Pre-existing dev environment issue
   - Need to resolve protobuf version conflict

3. **Service Broker not implemented:** `get_sql_server_notify_params()` helper exists
   - Full Service Broker implementation in dispatcherd pending
   - Placeholder for future async notification support

## Comparison to Alternative Approaches

| Approach | Migration Files | Maintenance | Risk | Status |
|----------|----------------|-------------|------|--------|
| **1. Modify historical migrations** | Single tree, modified | Low | High (hash conflicts) | Rejected |
| **2. Parallel mssql_migrations/** | Duplicated | High (sync burden) | Low | Fallback option |
| **3. Convert at end** | Unchanged + new | Low | N/A | Not viable (fresh MS SQL fails) |
| **4. Custom SchemaEditor** | Unchanged | Low (one-time) | Medium | **SELECTED** ✅ |

**Approach 4 wins because:**
- Most elegant solution
- Zero migration file duplication
- No ongoing sync maintenance
- Centralized conversion logic
- Easy to test and debug

## References

- **JIRA:** AAP-98732 (formerly ANSTRAT-1887)
- **Design Spec:** [docs/superpowers/specs/2026-10-19-mssql-support-design.md](superpowers/specs/2026-10-19-mssql-support-design.md)
- **Comprehensive Plan:** `/home/bhavenst/.claude/plans/misty-zooming-hinton.md`
- **MS SQL Index Limit:** 900 bytes; nvarchar = 2 bytes/char → 450 chars max
- **Django SchemaEditor Docs:** https://docs.djangoproject.com/en/stable/ref/schema-editor/
- **mssql-django:** https://github.com/microsoft/mssql-django
