# MS SQL Server JSONField Compatibility

## Overview

MS SQL Server and PostgreSQL handle JSONField differently. This document outlines the differences and our approach to ensuring compatibility.

## Key Differences

### 1. Storage Type

| Database | Storage Type | Notes |
|----------|-------------|-------|
| PostgreSQL | `jsonb` (binary) or `json` (text) | Native JSON type with validation |
| MS SQL Server | `nvarchar(max)` | Text column, validated via CHECK constraint |

### 2. JSON Validation

| Database | Validation Mechanism | When Applied |
|----------|---------------------|--------------|
| PostgreSQL | Built into JSON type | On INSERT/UPDATE |
| MS SQL Server | `ISJSON(column)=1` CHECK constraint | On INSERT/UPDATE (if constraint exists) |

**Our Decision:** Removed ISJSON CHECK constraint from MS SQL Server to support encrypted JSONFields.

### 3. Default Values

Both databases handle `default=dict` and `default=list` correctly:
- Empty dict `{}` → stored as `"{}"` → retrieved as Python `dict`
- Empty list `[]` → stored as `"[]"` → retrieved as Python `list`

### 4. Query Operators

**PostgreSQL JSON Operators:**
- `->`, `->>`, `@>`, `<@`, `?`, `?|`, `?&` (native JSON operators)
- Django translates lookups like `__contains` to these operators

**MS SQL Server JSON Functions:**
- `JSON_VALUE()`, `JSON_QUERY()`, `OPENJSON()`, `FOR JSON`
- Django's mssql-django translates lookups to these functions

**django-ansible-base Usage:**
- ✅ No JSON-specific operators used (`__contains`, `__has_key`, etc.)
- ✅ Only basic field access and assignment
- **Risk: Low** - We don't use advanced JSON query features

### 5. Indexing

| Database | JSON Indexing |
|----------|--------------|
| PostgreSQL | GIN indexes on JSONB columns |
| MS SQL Server | Cannot index nvarchar(max); requires computed columns |

**django-ansible-base:**
- ✅ No JSONFields have `db_index=True`
- ✅ No JSONFields in Index definitions
- **Risk: None** - We don't index JSON columns

## JSONFields in django-ansible-base

| Model | Field | Encrypted? | Default | Null? | Notes |
|-------|-------|-----------|---------|-------|-------|
| AuthenticatorUser | extra_data | ✅ Yes | dict | No | **Main concern** - encryption breaks ISJSON |
| AuthenticatorUser | claims | ❌ No | dict | No | OAuth claims from provider |
| AuthenticatorUser | last_login_map_results | ❌ No | list | No | Map evaluation results |
| Authenticator | configuration | ❌ No | dict | No | Plugin configuration |
| AuthenticatorMap | triggers | ❌ No | dict | No | Trigger conditions |
| Entry | changes | ❌ No | None | Yes | Activity stream change tracking |
| AAPFlag | labels | ❌ No | list | Yes | Feature flag labels |

## Compatibility Concerns

### ✅ RESOLVED: Encrypted JSONField

**Problem:** Encrypted data is not valid JSON, fails `ISJSON()` check.

**Solution:** Removed `ISJSON()` CHECK constraint from our custom MS SQL backend.

**Impact:** 
- Encrypted JSONFields work on MS SQL Server
- Non-encrypted JSONFields also work (no validation on either DB now)
- **Consistent behavior** across PostgreSQL and MS SQL Server

### ⚠️ TO TEST: Default Value Serialization

**Concern:** `default=dict` and `default=list` callables

**PostgreSQL behavior:**
```python
field = models.JSONField(default=dict)  # Creates new {} for each instance
```

**MS SQL Server behavior:**
```python
field = models.JSONField(default=dict)  # Creates new {} for each instance
```

**Action Items:**
- ✅ Verify empty dict/list defaults work on MS SQL
- ✅ Verify no shared reference issues (default={} creates new object each time)

### ⚠️ TO TEST: NULL vs Empty Object

**Concern:** `null=True` fields with None vs {} vs []

**Test cases:**
1. Save `changes=None` → fetch → should be `None`
2. Save `changes={}` → fetch → should be `{}`
3. Save `changes=[]` → fetch → should be `[]`
4. Filter `changes__isnull=True` → should find None values only
5. Filter `changes__isnull=False` → should find {} and [] but not None

### ⚠️ TO TEST: Large JSON Data

**Concern:** MS SQL `nvarchar(max)` has 2GB limit (1GB for actual data)

**PostgreSQL:** No practical limit for JSONB

**MS SQL Server:** `nvarchar(max)` can store up to ~1GB

**Typical sizes in django-ansible-base:**
- `extra_data` (OAuth): Usually < 5KB
- `claims`: Usually < 2KB  
- `configuration`: Usually < 10KB
- `changes` (activity stream): Usually < 50KB

**Action Items:**
- ✅ Document that MS SQL has 1GB limit for JSON data
- ⚠️ Test with realistically large JSON payloads
- ⚠️ Consider monitoring for approaching limits

## Testing Checklist

### Basic Functionality
- [x] Create model with JSONField default=dict
- [x] Create model with JSONField default=list
- [ ] Create model with JSONField null=True, value=None
- [x] Save and retrieve JSON data
- [x] Verify type preservation (dict/list/None)

### Encrypted JSONField
- [ ] Save encrypted JSON to `extra_data`
- [ ] Retrieve and decrypt `extra_data`
- [ ] Verify no ISJSON constraint violation

### Edge Cases
- [ ] Very large JSON (>100KB)
- [ ] Deeply nested JSON (>10 levels)
- [ ] JSON with special characters (unicode, quotes, backslashes)
- [ ] Empty values: {}, [], "", None

### Query Behavior
- [ ] Filter on JSONField=None
- [ ] Filter on JSONField={}
- [ ] Exclude JSONField__isnull=True
- [ ] Update JSONField value
- [ ] Bulk operations with JSONField

## Recommendations

### 1. Add Integration Tests

Create test cases that run on both PostgreSQL and MS SQL Server:

```python
class JSONFieldCompatibilityTest(TestCase):
    databases = ['default']
    
    def test_encrypted_json_field(self):
        """Encrypted JSONField should work on both databases."""
        # Test extra_data encryption/decryption
        pass
    
    def test_null_vs_empty(self):
        """NULL vs {} vs [] should behave consistently."""
        pass
    
    def test_default_factories(self):
        """default=dict should create new instances."""
        pass
```

### 2. Document Limitations

In user-facing MS SQL Server documentation:

> **JSONField Limitations**
> 
> When using MS SQL Server:
> - JSONField data is stored as text (nvarchar(max))
> - Maximum size: ~1GB per field
> - No JSON-specific query operators (use PostgreSQL for advanced JSON queries)
> - JSON validation is disabled to support encrypted JSONFields

### 3. Monitor for Issues

Watch for:
- Application errors related to JSON serialization/deserialization
- Size limit warnings (approaching 1GB)
- Performance differences in JSON-heavy operations

## References

- [Django JSONField Documentation](https://docs.djangoproject.com/en/stable/ref/models/fields/#jsonfield)
- [MS SQL JSON Functions](https://learn.microsoft.com/en-us/sql/relational-databases/json/json-data-sql-server)
- [PostgreSQL JSON Types](https://www.postgresql.org/docs/current/datatype-json.html)
- [mssql-django JSONField Implementation](https://github.com/microsoft/mssql-django)
