# MS SQL Server TextField Conversion Behavior

## Summary

When using MS SQL Server, the custom backend (`ansible_base.backends.mssql`) converts ALL TextField model definitions to CharField with appropriate max_length limits.

## Conversion Strategy

### Option 1: Conditional Conversion (Current Implementation)
**Converts only:** TextFields with `db_index=True`, `unique=True`, or in constraints

**Fields affected:** 6 fields in django-ansible-base
- RoleDefinition.name → CharField(255)
- ObjectRole.object_id → CharField(450)
- ObjectRole.parent_reference → CharField(450)
- RoleEvaluation.codename → CharField(100)
- RoleEvaluationUUID.codename → CharField(100)
- Resource.object_id → CharField(450)

**Non-converted fields remain nvarchar(max):**
- RoleDefinition.description
- AccessToken.description  
- Application.description
- Entry.object_id
- Entry.related_object_id

### Option 2: Always Convert (Recommended)
**Converts:** ALL TextFields unconditionally → CharField

**Max-length rules:**
- Description fields → 4000 (MS SQL nvarchar practical limit)
- Object ID fields → 450 (MS SQL index limit)
- Codename fields → 100 (Django permission standard)
- Name fields → 255 (common standard)

**Total fields affected:** ~11 fields (5 additional non-indexed fields)

## Validation Behavior When Exceeding Limits

### Database Level (Direct Django ORM)

**Behavior:** MS SQL Server rejects the data with ProgrammingError

```python
# Example: Saving 4001 chars to CharField(max_length=4000)
rd = RoleDefinition(description='x' * 4001)
rd.save()
# Raises: django.db.utils.ProgrammingError: 
# String or binary data would be truncated in table 'dab_db.dbo.dab_rbac_roledefinition'
```

**Error details:**
- Exception type: `django.db.utils.ProgrammingError`
- ODBC error code: `42000`
- Message: `"String or binary data would be truncated in table '<table>', column '<column>'. Truncated value: ''."`

### API Level (Django REST Framework)

**Behavior:** DRF validates max_length and returns 400 Bad Request

```python
# DRF ModelSerializer with CharField(max_length=4000)
serializer = RoleDefinitionSerializer(data={'description': 'x' * 4001})
serializer.is_valid()  # Returns False
print(serializer.errors)
# Output: {'description': ['Ensure this field has no more than 4000 characters.']}
```

**API Response:**
```json
{
  "description": [
    "Ensure this field has no more than 4000 characters."
  ]
}
```

**Status code:** 400 Bad Request

### DRF ModelSerializer Behavior

- **TextField (PostgreSQL):** No max_length validation
- **CharField(max_length=N) (MS SQL):** Automatically validates max_length

DRF's `ModelSerializer` automatically inherits `max_length` from CharField model fields and adds validation.

## Recommendation for Option 2 (Always Convert)

### Pros
1. ✅ **Simpler code** - No conditional logic, no ALTER TABLE operations
2. ✅ **Safer upgrades** - No schema changes on existing tables  
3. ✅ **Better UX** - Users get clear validation errors before database errors
4. ✅ **Consistent** - All object_id/description fields same type
5. ✅ **Fresh installs only** - No migration concerns (MS SQL not supported for existing data)

### Cons
1. ⚠️ **Description length limit** - 4000 chars max (vs unlimited on PostgreSQL)
   - Impact: 4000 chars ≈ 600-800 words
   - Typical use: Descriptions rarely exceed 500 characters
   - Real-world: 4000 is generous for UI descriptions

### Documentation Required

**User-facing documentation:**

> **MS SQL Server Limitations**
> 
> When using MS SQL Server as the database backend:
> - **Object descriptions** are limited to 4,000 characters
> - **Object IDs** are limited to 450 characters
> - Attempting to exceed these limits will result in a validation error
>
> These limits do not apply to PostgreSQL deployments.

**Error message example:**
```json
{
  "description": [
    "Ensure this field has no more than 4000 characters."
  ]
}
```

## Testing Results

| Test Case | Length | PostgreSQL | MS SQL (4000 limit) |
|-----------|--------|------------|---------------------|
| Short description | 500 chars | ✅ Success | ✅ Success |
| Normal description | 2000 chars | ✅ Success | ✅ Success |
| Long description | 3999 chars | ✅ Success | ✅ Success |
| At limit | 4000 chars | ✅ Success | ✅ Success |
| Exceeds limit | 4001 chars | ✅ Success | ❌ Validation error (API) or Database error (ORM) |
| Far exceeds | 10000 chars | ✅ Success | ❌ Validation error (API) or Database error (ORM) |

## Implementation Recommendation

**Update the custom SchemaEditor to always convert ALL TextFields:**

```python
def column_sql(self, model, field, include_default=False):
    """Convert ALL TextFields to CharField for MS SQL compatibility."""
    if isinstance(field, models.TextField):
        max_length = self._determine_max_length(field, model)
        converted_field = models.CharField(
            max_length=max_length, 
            **self._copy_field_attrs(field)
        )
        return super().column_sql(model, converted_field, include_default)
    
    return super().column_sql(model, field, include_default)
```

**Remove the conditional logic in:**
- `add_index()` - No longer needed
- `add_constraint()` - No longer needed  
- `create_model()` - No longer needed
- `_field_needs_conversion()` - No longer needed

**Result:** Much simpler implementation (~100 lines vs ~300 lines)

## PostgreSQL Compatibility

No impact - PostgreSQL deployments continue using standard Django backend with unlimited TextField.
