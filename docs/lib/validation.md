# Data validation

django-ansible-base provides some basic validation tools. These reside in `ansible_base.lib.utils.validation`.
The following items are available from the validation library:

`ansible_base.lib.utils.validation.VALID_STRING` this is a common string which says say:
```
Must be a valid string
```

`ansible_base.lib.utils.validation.validate_url` this is similar to the validate_url in django but has a parameter for `allow_plain_hostname: bool = False` which means you can have a url like `https://something:443/testing`.

`ansible_base.lib.utils.validation.validate_url_list` this is a convince method which takes an array of urls and validates each of them using its own validate_url method.


# CleanTextMixin — text input validation for serializers

`CleanTextMixin` is a drop-in mixin for DRF `ModelSerializer` subclasses that
automatically rejects unsafe characters and patterns in text fields. It applies
two validation tiers:

| Tier | Applies to | Strategy |
|------|-----------|----------|
| **Tier 1** | Name-type fields (`name`, `username`, `hostname` by default) | Strict character allowlist |
| **Tier 2** | All other `CharField` / `TextField` columns | Dangerous-pattern blocklist |

## Quick start

```python
from ansible_base.lib.serializers.mixins import CleanTextMixin
from rest_framework import serializers

class MyModelSerializer(CleanTextMixin, serializers.ModelSerializer):
    class Meta:
        model = MyModel
        fields = '__all__'
```

**MRO matters:** `CleanTextMixin` must appear *before* `ModelSerializer` (or any
other base) in the class definition so that its `validate()` method runs first
in the method resolution order.

## How field discovery works

The mixin inspects the model's `_meta.get_fields()` at validation time and
selects fields whose `get_internal_type()` returns `"CharField"` or
`"TextField"`. This deliberately excludes format-constrained subclasses like
`SlugField` and `URLField` (which override `get_internal_type()` and have their
own validators), while automatically catching custom free-text subclasses such
as `EncryptedTextField` that inherit the base type.

## Tier 1 — name allowlist

Fields whose name appears in the `name_fields` set are validated against a
strict regex allowlist:

```
^[\w][\w .@-]{0,511}\Z
```

This permits:
- Letters (including Unicode word characters via `\w`)
- Digits
- Spaces, hyphens (`-`), underscores (`_`), dots (`.`), and `@`
- Must start with a letter, digit, or underscore
- Maximum 512 characters

Values are NFC-normalized before matching so that composed and decomposed
Unicode representations are treated identically.

**Error message:**
> Enter a valid resource name. Only letters, numbers, spaces, hyphens,
> underscores, dots, and @ are allowed. Must start with a letter, number,
> or underscore. Maximum 512 characters.

## Tier 2 — dangerous pattern blocklist

All other text fields are checked against a compiled regex that catches:

| Category | Examples |
|----------|----------|
| Control characters | Null bytes (`\x00`), C0/C1 controls, zero-width joiners, BOM, bidirectional overrides |
| Dangerous HTML tags | `<script>`, `<iframe>`, `<object>`, `<embed>`, `<form>`, `<base>`, `<meta>`, `<link>`, `<svg>`, `<math>`, `<template>` (including fullwidth `＜` variants) |
| Event handlers | `onerror=`, `onclick=`, and other `on*=` attributes |
| Unsafe URI schemes | `javascript:`, `vbscript:`, `data:` |
| Shell substitution | `$(...)`, `${...}` |
| Template injection | `{{ }}`, `{% %}` (Jinja2 / Django template syntax) |

Safe HTML like `<b>`, `<em>`, and `<p>` is **not** blocked.

**Error message:**
> This field can't include HTML tags, script markup, unsafe URI schemes,
> shell syntax, or control characters.

## Grandfather behavior

On **update** (when `self.instance` is set), the mixin compares each field's
submitted value against the current stored value. If they are identical, that
field is skipped — even if the existing value would fail validation. This
prevents blocking edits to unrelated fields on records that pre-date the
validation rules.

On **create**, all text fields in the submitted data are validated.

Partial updates (`partial=True`) only validate fields that are present in the
request payload.

## Customization

### Adding service-specific name fields

If your service has fields that should receive Tier 1 (allowlist) treatment
beyond the defaults (`name`, `username`, `hostname`), extend `name_fields`:

```python
from ansible_base.lib.serializers.mixins import CleanTextMixin
from ansible_base.lib.utils.validation import DEFAULT_NAME_FIELDS

class MySerializer(CleanTextMixin, serializers.ModelSerializer):
    name_fields = DEFAULT_NAME_FIELDS | {'display_name', 'label'}

    class Meta:
        model = MyModel
        fields = '__all__'
```

### Excluding fields from validation

Fields that legitimately contain HTML, template syntax, or other structured
content (e.g., Jinja2 templates, custom login HTML) can be excluded:

```python
class JobTemplateSerializer(CleanTextMixin, serializers.ModelSerializer):
    excluded_fields = frozenset({'extra_vars', 'custom_login_info'})

    class Meta:
        model = JobTemplate
        fields = '__all__'
```

Excluded fields bypass both Tier 1 and Tier 2 validation entirely.

## Error reporting

When multiple fields fail validation, all errors are collected and returned in a
single `ValidationError` keyed by field name:

```json
{
    "name": ["Enter a valid resource name. ..."],
    "description": ["This field can't include HTML tags, ..."],
    "extra_field": ["This field can't include HTML tags, ..."]
}
```

## Known limitations

- **DRF serializers only.** The validators run in the serializer's `validate()`
  method. Code that creates or updates records via `Model.objects.create()`,
  `Model.save()`, or raw SQL bypasses these checks entirely. The mixin is not a
  substitute for database-level constraints. For new models, prefer model-level
  validators (see below).
- **SlugField / URLField excluded.** These format-constrained subclasses have
  their own validators and are intentionally skipped.
- **Regex-based detection.** Tier 2 uses pattern matching, not a full HTML
  parser. Novel obfuscation techniques may not be caught; defense in depth
  (output encoding, CSP headers) is still necessary.


# Model-level validators — recommended for new models and fields

The `validate_resource_name` and `validate_free_text` functions are exported as
public API from `ansible_base.lib.utils.validation` and can be used directly as
Django model field validators:

```python
from django.db import models
from ansible_base.lib.utils.validation import validate_resource_name, validate_free_text

class MyNewModel(models.Model):
    name = models.CharField(max_length=512, validators=[validate_resource_name])
    description = models.TextField(default='', validators=[validate_free_text])
```

## Why prefer model-level validation for new fields

`CleanTextMixin` operates at the serializer layer, which means it only fires on
requests that pass through a DRF serializer. Model-level validators are
stronger because Django's `full_clean()` runs them on **every code path**:

- API requests (via DRF serializers that call `full_clean()`)
- Management commands
- Bulk imports
- Signal handlers
- Direct ORM `save()` calls (when the caller invokes `full_clean()` first)

This prevents unsafe data from entering the database through non-API paths — a
gap that serializer-only validation cannot close.

## When to use which approach

| Scenario | Approach |
|----------|----------|
| **New model / new field** | Add `validators=[validate_resource_name]` or `validators=[validate_free_text]` directly on the model field. No serializer mixin needed. |
| **Existing model with legacy data** | Use `CleanTextMixin` on the serializer. Its grandfather behavior lets existing records keep their current values while blocking new violations through the API. |
| **Existing model, new field added** | Add the validator on the model field. The field has no legacy data, so grandfathering is not needed. |

The two approaches use the same underlying validators, so the rules (Tier 1
allowlist, Tier 2 blocklist) are identical regardless of where they run.


# Validation callback for role assignment

Apps that utilize django-ansible-base may wish to add extra validation when assigning roles to actors (users or teams).

For this, django-ansible-base will call out to `validate_role_assignment` method that defined on the object that being assigned.

The signature of this callback is

`validate_role_assignment(self, actor, role_definition, **kwargs)`

This method is reponsible for raising the appropriate exception if necessary, for example,

```python
from rest_framework.exceptions import ValidationError
class MyDjangoModel:
    def validate_role_assignment(self, actor, role_definition, **kwargs):
        raise ValidationError({'detail': 'Role assignment not allowed.'})
```

Note, if you want the exception to result in a HTTP 400 or 403 response, you can raise django rest framework exceptions instead of django exceptions.
