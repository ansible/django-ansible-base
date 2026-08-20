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
validates input and rejects violations when enforcement is enabled for unsafe characters and patterns in text fields. It applies
two validation tiers:

| Tier | Applies to | Strategy |
|------|-----------|----------|
| **Tier 1** | Name-type fields (`name`, `username`, `hostname` by default) | Strict character allowlist |
| **Tier 2** | All other `CharField` / `TextField` columns | Dangerous-pattern blocklist |

## Platform toggle — `ENHANCED_INPUT_VALIDATION_ENABLED`

CleanTextMixin is controlled by the install-time setting
`ENHANCED_INPUT_VALIDATION_ENABLED` (default: `False`).

| Value | Behavior |
|-------|----------|
| `False` (default) | Validation logic runs and violations are logged at WARNING level, but no `ValidationError` is raised — requests proceed normally. |
| `True` | Full Tier 1/Tier 2 validation is enforced. Invalid input is rejected with a `ValidationError`. |

This setting is defined at install time and propagated to all platform
components (Controller, EDA, Hub, Gateway). Changing it requires reinstalling
AAP. When the toggle is off, audit logs still capture every violation, giving
operators visibility into what would be rejected before enabling enforcement.

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
strict regex allowlist using Unicode general categories (via the `regex`
library):

```
^[\p{L}\p{N}_][\p{L}\p{N}\p{M}_ .@\-]{0,511}\Z
```

This permits:
- Letters (`\p{L}`) — all Unicode letters across scripts
- Numbers (`\p{N}`) — all Unicode digits and numerals
- Combining marks (`\p{M}`) — accents, vowel signs, and similar diacritics
  needed for Indic scripts and other writing systems
- Spaces, hyphens (`-`), underscores (`_`), dots (`.`), and `@`
- Must start with a letter, number, or underscore
- Maximum 512 characters

The pattern string is available as `RESOURCE_NAME_PATTERN`.  For frontend
validation, replace the Python-specific `\Z` anchor with `$` (which behaves
identically in JavaScript without the `m` flag):

```js
/^[\p{L}\p{N}_][\p{L}\p{N}\p{M}_ .@\-]{0,511}$/u
```

Values are NFC-normalized before matching so that composed and decomposed
Unicode representations are treated identically.

In addition to the allowlist, names are checked for:
- **Invisible characters** (`\p{Default_Ignorable_Code_Point}`) — variation
  selectors, zero-width spaces, soft hyphens, and similar characters that are
  invisible but can enable spoofing attacks.
- **Zalgo text** — five or more consecutive combining marks, which create
  visually disruptive stacked diacritics.

**Error messages:**
> Enter a valid name. Use letters, numbers, spaces, hyphens (-), underscores (_),
> dots (.), and @. Start with a letter, number, or underscore. Max 512 characters.

> This field can't include invisible characters.

> Too many combining marks.

## Tier 2 — dangerous pattern blocklist

All other text fields are checked for the following categories of dangerous
content. HTML detection uses `nh3` (a real HTML parser based on html5ever)
rather than regex, so it cannot be evaded by tag obfuscation, unusual
whitespace, or encoding tricks.

Every input is also checked in HTML-entity-decoded and percent-decoded form
(up to three decode passes) and then NFKC-normalized (which folds fullwidth
characters like `＜` to their ASCII equivalents), so encoded payloads like
`&#60;script&#62;` or `%3Cscript%3E` and fullwidth obfuscations like
`ｊａｖａｓｃｒｉｐｔ：` are caught across all checks.

| Category | Detection method | Examples |
|----------|-----------------|----------|
| Control characters | Regex (intentionally selective range) | C0/C1 controls (except tab, LF, and CR), zero-width space, directional overrides (LRO/RLO), invisible math operators, deprecated formatting chars, BOM, interlinear annotations. Allows ZWNJ/ZWJ, bidi marks/embeddings/isolates, and soft hyphen for multilingual support. |
| HTML tags | `nh3` parser (all tags rejected) | `<script>`, `<iframe>`, `<b>`, `<img>`, `<p>`, any HTML tag (including fullwidth `＜` variants via NFKC normalization) |
| Unsafe URI schemes | Regex (with WHATWG-aware whitespace stripping) | `javascript:`, `vbscript:`, and `data:` URIs with all WHATWG-defined script-capable MIME types: `text/html`, `text/javascript` (incl. versioned `1.0`–`1.5`), `text/xml`, `text/ecmascript`, `text/x-javascript`, `text/x-ecmascript`, `text/jscript`, `text/livescript`, `application/javascript`, `application/xml`, `application/xhtml+xml`, `application/ecmascript`, `application/x-javascript`, `application/x-ecmascript`, `image/svg+xml`. Includes tab/LF/CR-obfuscated variants like `jav\tascript:`. |
| Shell substitution | Regex | `$(...)`, `${...}` |
| Template injection | Regex | `{{ }}`, `{% %}` (Jinja2 / Django template syntax) |

**All** HTML tags are rejected, not just a dangerous subset. Fields that
legitimately contain HTML (e.g. custom login pages, Jinja2 templates) should
be listed in `excluded_fields`.

### Known false positive: `javascript:` / `vbscript:` in prose

Text containing the word "JavaScript" or "VBScript" followed by a colon
(e.g., `"This uses JavaScript: see docs for details"`) will be rejected by the
unsafe URI scheme check. This is a known trade-off — there is no reliable
regex-only way to distinguish prose from a URI attack in all cases, and these
patterns are uncommon in AAP field values. The slightly overzealous check is
preferable to introducing a potential bypass.

**Error messages** (specific to the pattern that triggered rejection):
> This field can't include control characters.

> This field can't include HTML tags, script markup, or unsafe URI schemes.

> This field can't include shell or template syntax.

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

## JSONField validation

Starting with this version, `CleanTextMixin` also validates **string values
inside JSONFields**. This catches dangerous content in credential inputs,
notification configs, authenticator configs, and similar structured data.

### How it works

After the text-field loop, the mixin discovers all model fields with
`get_internal_type() == 'JSONField'`. For each JSONField present in the
submitted data:

- **Dict values:** recursively traverses nested dicts and lists, validating
  every string value using Tier 2 (dangerous-pattern blocklist). Non-string,
  non-container values (integers, booleans, `None`) are skipped.
- **List values:** recursively traverses list items — validating bare strings,
  recursing into nested dicts, and recursing into nested lists.

Recursion is capped at a depth of 10 to prevent pathological inputs from
causing excessive processing.

### Grandfathering at every nesting level

On **update**, each string value is compared against the corresponding value in
the stored data, following the same path through the nested structure. Only
changed values are validated — unchanged values are grandfathered even if they
contain content that would fail validation. This comparison works at every
nesting depth, not just the top level.

For lists, grandfathering compares by index (item at position N in the
submitted list is compared against item at position N in the stored list).

### Excluding entire JSONFields

Add the field name to `excluded_fields` to skip the entire JSONField:

```python
class JobTemplateSerializer(CleanTextMixin, serializers.ModelSerializer):
    excluded_fields = frozenset({'extra_vars'})

    class Meta:
        model = JobTemplate
        fields = '__all__'
```

### Excluding specific sub-keys

Some sub-keys legitimately contain content that would trigger the blocklist
(e.g., PEM-encoded keys, template syntax). Use `excluded_json_keys` to skip
specific sub-keys within a JSONField:

```python
class CredentialSerializer(CleanTextMixin, serializers.ModelSerializer):
    excluded_json_keys = {
        'inputs': frozenset({'ssh_key_data', 'ssh_key_unlock'}),
        'notification_configuration': frozenset({'headers'}),
    }

    class Meta:
        model = Credential
        fields = '__all__'
```

The mapping keys are JSONField names; the values are frozensets of sub-key
names to skip. Excluded sub-keys are skipped at **every** nesting depth, not
just the top level — if `ssh_key_data` is excluded, it is skipped wherever it
appears in the JSON structure.

### Error format

Errors use nested dict format keyed by the JSONField name, with sub-keys
identifying the problematic field:

```json
{
    "inputs": {
        "username": ["This field can't include HTML tags, ..."],
        "host": ["This field can't include HTML tags, ..."]
    }
}
```

For lists, the sub-key includes the index:

```json
{
    "links": {
        "[1].url": ["This field can't include HTML tags, ..."]
    }
}
```

For nested structures, dot-separated paths identify the location:

```json
{
    "config": {
        "database.host": ["This field can't include HTML tags, ..."],
        "endpoints[0].url": ["This field can't include HTML tags, ..."]
    }
}
```

This nested format is compatible with DRF's standard error handling and allows
frontend form frameworks (e.g., react-hook-form) to map errors to the correct
input fields.

### Authenticator configuration exclusions

`AuthenticatorSerializer` sets `excluded_json_keys` on the `configuration`
JSONField to skip encrypted sub-keys and structured pass-through data:

```python
excluded_json_keys = {
    'configuration': frozenset({
        'SECRET',
        'BIND_PASSWORD',
        'SP_PRIVATE_KEY',
        'ADDITIONAL_UNVERIFIED_ARGS',
    }),
}
```

**Encrypted fields** — These sub-keys appear in each plugin's
`configuration_encrypted_fields`. Their cleartext values (passwords, private
keys) may legitimately contain patterns matching the Tier 2 blocklist (e.g.,
an LDAP bind password containing `${LDAP_PASS}`). On update, the serializer's
`to_internal_value()` replaces the `ENCRYPTED_STRING` sentinel with the stored
value, so unchanged secrets would be grandfathered. The exclusion is needed
for create, where cleartext values are submitted.

| Key | Plugins | Content |
|-----|---------|---------|
| `SECRET` | GitHub (all variants), Google OAuth2, OIDC, Keycloak, AzureAD, TACACS, Radius | OAuth2 client secret or shared secret |
| `BIND_PASSWORD` | LDAP | LDAP bind password |
| `SP_PRIVATE_KEY` | SAML | PEM-encoded service provider private key |

**Structured data (out of scope)** — `ADDITIONAL_UNVERIFIED_ARGS` is a
JSONField on every plugin (inherited from `BaseAuthenticatorConfiguration`)
that accepts arbitrary JSON passed directly to the authenticator without
validation. Per the input validation scope, validation of structured data
content (YAML/JSON) is excluded.

**Keys that do NOT need exclusion:**

Other structured sub-keys (`ORG_INFO`, `TECHNICAL_CONTACT`, `SUPPORT_CONTACT`,
`SP_EXTRA`, `SECURITY_CONFIG`, `EXTRA_DATA`, `GROUP_TYPE_PARAMS`,
`CONNECTION_OPTIONS`, `GROUP_SEARCH`, `USER_SEARCH`, `USER_ATTR_MAP`,
`JWT_ALGORITHMS`, `JWT_DECODE_OPTIONS`, `SCOPE`) store dicts or lists, not
top-level strings. The mixin's `_validate_json_dict()` recurses into dict and
list values and validates any string leaf values it finds (e.g.
`TECHNICAL_CONTACT.emailAddress`) with the same Tier 2 blocklist as top-level
fields, so no explicit exclusion is required — legitimate values (names,
emails, LDAP attribute names) are expected to pass Tier 2 validation without
triggering false positives.

Certificate fields (`SP_PUBLIC_CERT`, `IDP_X509_CERT`, `PUBLIC_KEY`) are
strings but contain PEM-encoded data (base64 + headers) that does not match
any pattern in `DANGEROUS_PATTERNS`. No exclusion needed.

All remaining string sub-keys (`NAME`, `KEY`, `HOST`, `SERVER`, SAML attribute
names, OIDC claim names, etc.) are validated by the mixin as defense-in-depth.
Most are format-constrained by their identity provider, but they accept
user-provided input and should be scanned for injection patterns.

When adding a new authenticator plugin with new
`configuration_encrypted_fields` entries, add the field names to
`excluded_json_keys` on `AuthenticatorSerializer`.

### AuthenticatorMap field exclusions

`AuthenticatorMapSerializer` sets `excluded_fields` to skip three CharField
fields from CleanTextMixin validation entirely:

```python
excluded_fields = frozenset({'organization', 'role', 'team'})
```

These fields support template expansion syntax for dynamic mapping rules.
Values like `{% for_attr_value(user_orgs) %}` and
`Organization {% for_attr_value(member_of) %}` are valid inputs that allow
authenticator maps to dynamically resolve organization, team, and role names
from user attributes at authentication time.

The `{% %}` pattern matches `DANGEROUS_PATTERNS` (template injection
category), so these fields must be excluded to avoid false positives.

The excluded field names match `_EXPANSION_FIELDS` defined in
`ansible_base.authentication.utils.authenticator_map`:

```python
_EXPANSION_FIELDS = ['organization', 'role', 'team']
```

The serializer's own `validate()` method already validates the expansion
syntax of these fields via `check_expansion_syntax()` — but this only
catches **malformed** expansion attempts (a value containing `{%` and `%}`
that doesn't match the `for_attr_value(...)` shape). The `name` field on
`AuthenticatorMap` is **not** excluded and receives Tier 1 validation.

**Scope.** `check_expansion_syntax()` only rejects malformed expansion
attempts, so literal (non-templated) values in these fields also bypass all
Tier 1/Tier 2 validation — the exclusion is field-wide, not conditional on
whether a given value actually uses expansion syntax. As with other
templated/structured configuration values in this doc, validating literal
content in these fields is accepted as out of scope rather than partially
enforced.

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
- **Defense in depth still required.** While Tier 2 uses nh3 (a real HTML
  parser) for tag detection and decoded-variant checks for bypass prevention,
  defense in depth (output encoding, CSP headers) is still necessary.


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
