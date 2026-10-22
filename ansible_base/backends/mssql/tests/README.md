# MS SQL Server Backend Tests

## Overview

This directory contains tests for the custom MS SQL Server backend, including:

- **TextField to CharField conversion** (schema editor)
- **JSONField compatibility** between PostgreSQL and MS SQL Server
- **Encrypted JSONField** handling

## Running Tests

### All MS SQL Backend Tests

```bash
# Using pytest (recommended)
pytest ansible_base/backends/mssql/tests/

# Using Django test runner
python manage.py test ansible_base.backends.mssql.tests
```

### Specific Test Classes

```bash
# JSONField compatibility tests only
pytest ansible_base/backends/mssql/tests/test_jsonfield_compatibility.py

# Schema editor tests only
pytest ansible_base/backends/mssql/tests/test_schema_editor.py
```

### Database-Specific Tests

Some tests are marked to run only on specific databases:

```python
@skipUnless(connection.vendor == 'microsoft', 'MS SQL Server only')
def test_mssql_specific():
    ...

@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL only')
def test_postgresql_specific():
    ...
```

### Run on Both Databases

To verify compatibility, run tests on both PostgreSQL and MS SQL Server:

```bash
# PostgreSQL
DJANGO_SETTINGS_MODULE=test_app.settings pytest ansible_base/backends/mssql/tests/test_jsonfield_compatibility.py

# MS SQL Server
DJANGO_SETTINGS_MODULE=test_app.settings_mssql pytest ansible_base/backends/mssql/tests/test_jsonfield_compatibility.py
```

## Test Coverage

### JSONField Compatibility Tests (17 tests)

#### JSONFieldBasicTest (3 tests)
- `test_default_dict_creates_new_instances` - Verify `default=dict` doesn't share references
- `test_default_list_creates_new_instances` - Verify `default=list` doesn't share references  
- `test_empty_dict_vs_none` - Distinguish between `{}`, `[]`, and `None`
- `test_query_null_vs_empty` - Filter behavior for NULL vs empty JSON

#### JSONFieldEncryptionTest (3 tests)
- `test_encrypted_jsonfield_round_trip` - Encrypt/decrypt cycle preserves data
- `test_encrypted_jsonfield_with_binary_data` - Binary data base64 encoding
- `test_no_isjson_constraint_on_encrypted_field` - **MS SQL only** - Verify no ISJSON constraint

#### JSONFieldSizeTest (2 tests)
- `test_large_json_payload` - Handle ~100KB JSON objects
- `test_deeply_nested_json` - Handle 20+ levels of nesting

#### JSONFieldEdgeCasesTest (4 tests)
- `test_special_characters` - Unicode, quotes, backslashes, newlines
- `test_empty_string_in_json` - Empty strings don't become NULL
- `test_numeric_values` - Preserve int/float types

#### JSONFieldBulkOperationsTest (2 tests)
- `test_bulk_create_with_jsonfield` - Bulk create with JSON data
- `test_bulk_update_jsonfield` - Bulk update JSON fields

#### JSONFieldDatabaseSpecificTest (3 tests)
- `test_database_vendor_detection` - Can detect PostgreSQL vs MS SQL
- `test_mssql_uses_nvarchar_max` - **MS SQL only** - Verify nvarchar(max) storage
- `test_postgresql_uses_jsonb` - **PostgreSQL only** - Verify jsonb storage

## Test Data Models Used

- **AuthenticatorUser** - encrypted `extra_data` JSONField
- **Authenticator** - `configuration` JSONField  
- **Entry** - nullable `changes` JSONField
- **ContentType** - for creating test Entry objects

## Known Issues / Expected Behavior

### Bulk Operations & Encryption

`bulk_create()` and `bulk_update()` bypass the model's `save()` method, so:
- Encryption does NOT happen in bulk operations
- Tests verify raw JSON handling, not encrypted JSON

For production use:
- Individual saves: encryption works
- Bulk operations: only use for non-encrypted JSONFields

### MS SQL Specific

- JSONField stored as `nvarchar(max)` (not native JSON type)
- No ISJSON() constraint (removed to support encryption)
- Maximum size: ~1GB per field (practical limit ~100MB recommended)

### PostgreSQL Specific

- JSONField stored as `jsonb` (binary JSON)
- Native JSON validation on insert
- GIN indexes supported (not used in django-ansible-base)

## Adding New Tests

When adding JSONField tests:

1. Consider both databases - test on PostgreSQL AND MS SQL Server
2. Test with encryption if relevant (AuthenticatorUser.extra_data)
3. Test NULL vs empty for nullable fields
4. Include edge cases (special chars, large data, nesting)
5. Mark database-specific tests with `@skipUnless`

Example:

```python
from unittest import skipUnless
from django.db import connection

class MyJSONFieldTest(TestCase):
    
    def test_cross_database(self):
        """This test runs on both databases."""
        pass
    
    @skipUnless(connection.vendor == 'microsoft', 'MS SQL only')
    def test_mssql_specific(self):
        """This test only runs on MS SQL Server."""
        pass
```

## CI/CD Integration

These tests should run in CI on both database backends:

```yaml
# .github/workflows/test.yml
strategy:
  matrix:
    database: [postgresql, mssql]

steps:
  - name: Run MS SQL backend tests
    run: |
      pytest ansible_base/backends/mssql/tests/
    env:
      DATABASE_ENGINE: ${{ matrix.database }}
```

## Debugging

### View SQL Queries

```python
from django.db import connection
from django.test.utils import override_settings

@override_settings(DEBUG=True)
def test_with_sql_logging(self):
    # ... test code ...
    
    # Print all queries
    for query in connection.queries:
        print(query['sql'])
```

### Check Constraints

```python
# MS SQL Server
with connection.cursor() as cursor:
    cursor.execute("""
        SELECT CONSTRAINT_NAME, CHECK_CLAUSE
        FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS
        WHERE TABLE_NAME = 'your_table'
    """)
    print(cursor.fetchall())
```

### Inspect Field Types

```python
# MS SQL Server
with connection.cursor() as cursor:
    cursor.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'your_table'
    """)
    print(cursor.fetchall())
```

## References

- [Django JSONField Documentation](https://docs.djangoproject.com/en/stable/ref/models/fields/#jsonfield)
- [MS SQL JSON Functions](https://learn.microsoft.com/en-us/sql/relational-databases/json/json-data-sql-server)
- [PostgreSQL JSON Types](https://www.postgresql.org/docs/current/datatype-json.html)
- [mssql-django JSONField](https://github.com/microsoft/mssql-django)
