# ORM-Direct Validation Bypass Paths

This document catalogs known code paths that write to the database via ORM methods
(Model.objects.create(), instance.save(), queryset.update(), bulk_create(), etc.)
rather than through DRF serializers, and therefore bypass CleanTextMixin validation.

The validation signal handler (`ansible_base.lib.utils.validation_signals.validation_bypass_logger`)
provides observability for **single-instance saves** (create(), save()) by logging validation
violations without blocking the save operation. **Bulk operations** (bulk_create(), bulk_update(),
queryset.update()) are not observable via this signal — see the "Known Limitations" section below.

## Why This Matters

CleanTextMixin enforces input validation at the serializer layer. Any code that
creates or updates model instances directly via the Django ORM bypasses this
validation. While this is sometimes intentional (e.g., management commands,
migrations), it can also be a security gap if untrusted data reaches these paths.

The signal handler detects these bypass writes and logs them for security
monitoring and compliance auditing.

## Known Bypass Paths

### 1. Management Commands

**Location:** Various `management/commands/*.py` files across apps

**Pattern:**
```python
# Example from a hypothetical management command
MyModel.objects.create(
    name=user_input_name,
    description=user_input_description
)
```

**Why it bypasses:** Management commands typically operate directly on models
for performance and to avoid serializer overhead.

**Risk level:** Low to Medium — depends on whether the command accepts untrusted input.

**Example locations:**
- Check any custom management commands in downstream services (Controller, EDA, Hub)
- Data migration scripts
- Bulk import utilities

### 2. Signal Handlers and Model Methods

**Location:** `*/models.py`, `*/signals.py` files

**Pattern:**
```python
@receiver(post_save, sender=RelatedModel)
def create_dependent_object(sender, instance, created, **kwargs):
    if created:
        DependentModel.objects.create(
            name=f"Auto-{instance.name}",
            parent=instance
        )
```

**Why it bypasses:** Signal handlers and model methods often create related
objects programmatically without going through serializers.

**Risk level:** Low — data is usually derived from existing validated objects,
not external input.

**Example locations:**
- `ansible_base/rbac/triggers.py` - RBAC object creation signals
- `ansible_base/resource_registry/signals/handlers.py` - Resource sync handlers
- Any model's `save()` override that creates related objects

### 3. Bulk Operations

**Location:** Data sync, import, and migration code

**Pattern:**
```python
# Bulk create for performance
objects_to_create = [
    MyModel(name=item['name'], description=item['description'])
    for item in external_data
]
MyModel.objects.bulk_create(objects_to_create)
```

**Why it bypasses:** `bulk_create()`, `bulk_update()`, and `update()` on querysets
do not trigger `full_clean()` or serializer validation.

**⚠️ Not detected by `validation_bypass_logger`:** Django does not send `post_save`
(or any) signal for `bulk_create()` or `bulk_update()` -- the signal this story adds
has no way to observe these writes at all. This is the same category of write used by
project sync, inventory source updates, and collection imports (the paths called out
as the primary motivation in this story's parent epic), so those specific operations
remain fully unobserved by this signal. The only real mitigation for this path is a
model-level validator on the field (see docs/lib/validation.md), which runs on
`full_clean()` regardless of how the object is saved -- but is not called by
`bulk_create()`/`bulk_update()` either unless the caller explicitly invokes it first.

**Risk level:** Medium to High — if external_data comes from untrusted sources
(API integrations, file imports, sync operations).

**Example locations:**
- Project sync operations (SCM imports)
- Inventory source updates (dynamic inventory imports)
- Collection imports (Ansible Galaxy sync)
- LDAP/SAML user sync operations

### 4. QuerySet update() Calls

**Location:** Batch update operations

**Pattern:**
```python
# Update multiple objects at once
MyModel.objects.filter(category='old').update(
    description='Migrated from old system'
)
```

**Why it bypasses:** QuerySet `update()` generates a single SQL UPDATE and
does not instantiate model objects or run validation.

**⚠️ Not detected by `validation_bypass_logger`:** Like `bulk_create()`/`bulk_update()`,
`QuerySet.update()` sends no signal, so this path is invisible to the signal added by
this story.

**Risk level:** Low to Medium — typically used for administrative changes with
fixed values, not external input.

**Example locations:**
- Data migrations
- Batch status updates
- Cache invalidation triggers

### 5. Migrations

**Location:** `*/migrations/*.py` files

**Pattern:**
```python
def forwards(apps, schema_editor):
    MyModel = apps.get_model('app_label', 'MyModel')
    MyModel.objects.create(name='default', description='System default')
```

**Why it bypasses:** Migrations use historical model classes and operate
outside the normal request/validation flow.

**Risk level:** Very Low — migration data is hardcoded or derived from the schema.

**Example locations:**
- Initial data migrations
- Backfill migrations for new fields

### 6. Test Fixtures and Factories

**Location:** `test_app/tests/**/test_*.py`, factory files

**Pattern:**
```python
# In tests
org = Organization.objects.create(name='TestOrg', description='<html>test</html>')
```

**Why it bypasses:** Tests often create objects directly for speed and to
test specific edge cases, including invalid data.

**Risk level:** None — test data does not reach production.

**Example locations:**
- Test fixtures in `test_app/tests/`
- Factory Boy factories (if used)
- Pytest fixtures

## Detection Strategy

**Scope: only `post_save`-firing writes on registered models.** The signal only ever
fires for models that have at least one serializer using `CleanTextMixin` -- every such
serializer registers its `Meta.model` (plus its `name_fields`/`excluded_fields`) with the
signal via `CleanTextMixin.__init_subclass__`. This is deliberate on two counts:

- It matches AC #1's literal scope ("models that are covered by `CleanTextMixin` in
  their serializers"), rather than checking every model in the process.
- It avoids false positives from *other* models that happen to get saved as a side
  effect of the original save -- for example, `resource_registry`'s `Resource` model is
  updated (and `.save()`d again) from a `post_save` receiver on many models. Without the
  registry, that cascade would itself fire `validation_bypass_logger` for `Resource`
  (which has no `CleanTextMixin` serializer), inflating the log with unrelated entries.

The `validation_bypass_logger` signal uses this detection flow:

1. **Check the model registry:** Skip immediately if `sender` has no registered
   `CleanTextMixin` serializer (see above)

2. **Check context variable:** Skip if save originated from a `CleanTextMixin`
   serializer's `.save()` call (prevents double-logging serializer-mediated writes --
   held for the duration of the actual persistence, not just `is_valid()`/`validate()`,
   so it also covers any `post_save` cascades triggered synchronously within that save)

3. **Check validation setting:** Skip if `ENHANCED_INPUT_VALIDATION_ENABLED` is False
   (no point logging violations when enforcement is off)

4. **Get text fields:** Use same field discovery as CleanTextMixin
   (`get_internal_type() in ('CharField', 'TextField')`), skipping any field name in
   the registered `excluded_fields`

5. **Validate each field:** Run `validate_resource_name` (Tier 1) or
   `validate_free_text` (Tier 2) on each text field value

6. **Log violations:** Emit WARNING log with structured data:
   - Resource type (app_label.ModelName)
   - Field name
   - Violation tier (Tier 1 / Tier 2)
   - Sanitized error message (NOT the raw value)
   - Caller info (module.function:line from stack inspection, skipping Django's
     save()/signal-dispatch frames and this module's own frames)

## Log Format

```
WARNING ansible_base.lib.utils.validation_signals: ORM bypass: validation rejected 'description' on test_app.Organization (violates Tier 2) [caller: my_app.views.create_org:42]: This field can't include HTML tags, script markup, or unsafe URI schemes.
```

**Structured fields:**
- `field_name`: The model field that failed validation
- `resource_type`: `app_label.ModelName`
- `tier`: "Tier 1" (name allowlist) or "Tier 2" (dangerous pattern blocklist)
- `caller`: `module.function:line` (from stack introspection)
- `reason`: Validator's error message (sanitized, no raw input)

## Remediation

When a bypass violation is logged:

1. **Investigate the caller:** The log includes the calling code location.
   Review that code to determine if it handles untrusted input.

2. **Assess risk:**
   - Low: Data is hardcoded or derived from validated sources
   - Medium: Data comes from semi-trusted sources (admin uploads, integrations)
   - High: Data comes from untrusted user input

3. **Remediate if needed:**
   - **Preferred:** Refactor to use a DRF serializer with CleanTextMixin
   - **Alternative:** Add model-level validators (see docs/lib/validation.md)
   - **Workaround:** Manually call validators before save:
     ```python
     from ansible_base.lib.utils.validation import validate_free_text
     validate_free_text(user_input)  # Raises ValidationError if invalid
     MyModel.objects.create(description=user_input)
     ```

4. **Document the decision:** If the bypass is intentional (e.g., migration
   with legacy data), add a code comment explaining why validation is skipped.

## Known Limitations

- **No coverage for bulk operations.** `bulk_create()`, `bulk_update()`, and
  `QuerySet.update()` never send `post_save` (Django does not fire signals for them),
  so `validation_bypass_logger` cannot see these writes at all. This includes the
  highest-risk paths named in this story's motivating epic: project sync, inventory
  source updates, and collection imports typically use one of these bulk APIs. The
  signal only observes per-instance saves (`Model.save()`, `Model.objects.create()`).
  Real protection for bulk paths requires a model-level validator on the field (see
  docs/lib/validation.md), and even that requires the caller to invoke `full_clean()`
  explicitly since `bulk_create()`/`bulk_update()` skip it too.

- **Scoped to models with a `CleanTextMixin` serializer.** The signal only checks
  models registered via `CleanTextMixin.__init_subclass__` (see Detection Strategy
  above). A model with no `CleanTextMixin` serializer anywhere in the codebase gets
  no observability from this signal, even if it has free-text fields that a service
  intends to protect later. As downstream services (Controller, EDA, Hub, Gateway)
  add `CleanTextMixin` to more serializers, more of their models come under this
  signal's coverage automatically -- but until a serializer exists, direct ORM writes
  to that model are invisible to it.

- **`excluded_fields` union across serializers.** If two different serializers for
  the same model configure different `excluded_fields`, the signal uses the *union* of
  both (a field excluded by either serializer is skipped for all ORM-direct saves of
  that model). This can under-report violations on a field that one serializer
  intentionally excludes (e.g., a Jinja2 template field) but another does not.

## Future Enhancements

- **Model-level validators:** New models should use model field validators
  (see docs/lib/validation.md) for defense-in-depth validation that covers
  all code paths, not just serializers.

- **Audit dashboard:** Aggregate bypass violation logs into a security
  dashboard for ongoing monitoring.

- **Policy enforcement:** For high-security deployments, consider making
  `ENHANCED_INPUT_VALIDATION_ENABLED=True` mandatory and blocking known
  bypass paths with custom model save() overrides that call full_clean().

## See Also

- [docs/lib/validation.md](validation.md) - CleanTextMixin documentation
- [ansible_base/lib/utils/validation.py](../../ansible_base/lib/utils/validation.py) - Validator implementations
- [ansible_base/lib/utils/validation_signals.py](../../ansible_base/lib/utils/validation_signals.py) - Signal handler implementation
