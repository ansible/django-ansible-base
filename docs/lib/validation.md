# Data validation

django-ansible-base provides some basic validation tools. These reside in `ansible_base.lib.utils.validation`.
The following items are available from the validation library:

`ansible_base.lib.utils.validation.VALID_STRING` this is a common string which says say:
```
Must be a valid string
```

`ansible_base.lib.utils.validation.validate_url` this is similar to the validate_url in django but has a parameter for `allow_plain_hostname: bool = False` which means you can have a url like `https://something:443/testing`.

`ansible_base.lib.utils.validation.validate_url_list` this is a convince method which takes an array of urls and validates each of them using its own validate_url method.

# Enhanced input validation

The sections below document tier 1/tier 2 text rules (`CleanTextMixin`, model
validators, OPTIONS hints). They are separate from the URL helpers above and
from the role-assignment callback at the end of this page.

## Tier 1 and tier 2 (shared rules)

DAB implements enhanced text validation as two tiers in
`ansible_base.lib.utils.validation`.

**Tier 1 is stricter than tier 2.** Tier 1 restricts which characters may appear
in a value (allowlist). Tier 2 allows most characters but rejects dangerous
patterns (blocklist). Name-type fields get tier 1 only; other text fields get
tier 2 only. The mixin never runs both on the same field.

| Tier | Typical fields | Validator | Strategy |
|------|----------------|-----------|----------|
| **Tier 1** | `name`, `username`, `hostname` (configurable) | `validate_resource_name` | Strict character allowlist |
| **Tier 2** | Other model `CharField` / `TextField` columns | `validate_free_text` | Dangerous-pattern blocklist |

Tier 2 checks (HTML, unsafe URI schemes, shell/template syntax, and related
patterns) are independent of the tier 1 regex. They simply do not run on fields
routed to tier 1.

**Tier 1 behavior** — `validate_resource_name()` in `validation.py`
(`RESOURCE_NAME_PATTERN` / `RESOURCE_NAME_RE`). On serializers, fields in
`name_fields` (default `DEFAULT_NAME_FIELDS`) use tier 1. Beyond the allowlist:
NFC normalization, rejection of invisible code points, and limits on combining
marks (Zalgo).

**Tier 2 behavior** — `validate_free_text()` in `validation.py` (HTML via
`nh3`, decode passes, pattern list). All HTML tags are rejected; use
`excluded_fields` for fields that legitimately contain HTML or template syntax.
Prose
like `JavaScript: …` can match unsafe-URI heuristics (documented trade-off in
code). String values inside `JSONField` payloads use tier 2 only when validated
through the serializer mixin (see [Grandfather behavior](#grandfather-behavior)
and [Known limitations](#known-limitations)).

## Choosing the validation layer

**Implemented path today:** DAB and consuming applications enforce these tiers on
API traffic through `CleanTextMixin` on DRF serializers—that is what DAB ships
and tests on existing models. Model field validators are optional guidance (not
platform-wide today); see [Model-level validation (guidance)](#model-level-validation-guidance).

| Scenario | Approach |
|----------|----------|
| **Existing model / legacy data** | `CleanTextMixin` on API serializers. |
| **New model or field** | `CleanTextMixin` on API serializers; optional model field validators when non-DRF paths must enforce the same rules (details below). |

## Enforcement toggle — `ENHANCED_INPUT_VALIDATION_ENABLED`

Whether invalid API input is **rejected** or only **logged** is controlled by
the platform install-time setting `ENHANCED_INPUT_VALIDATION_ENABLED` (default
`False` when unset). It is applied when the platform is installed or
reinstalled—not a value operators change at runtime. DAB reads it with
`ansible_base.lib.utils.settings.get_setting`.

| Value | Behavior |
|-------|----------|
| `False` (default) | Checks run; violations are logged at WARNING; requests are not rejected. |
| `True` | Same checks; invalid input raises `ValidationError`. |

When enforcement is off, logs still record violations so operators can see what
would be rejected before turning enforcement on.

This is an install-time platform setting, not a runtime DAB feature flag
(`ansible_base.feature_flags`).

`validate_resource_name` and `validate_free_text` always raise when they detect a
violation. Only `CleanTextMixin` applies the log-vs-reject policy above on API
traffic. See [Model-level validation (guidance)](#model-level-validation-guidance)
for how that differs from model field validators.

## Serializer-level validation

`CleanTextMixin` in `ansible_base.lib.serializers.mixins` applies tier 1/tier 2
during DRF serializer `validate()`. It also validates strings inside
`JSONField` payloads, supports **grandfathering** on legacy records, respects
`ENHANCED_INPUT_VALIDATION_ENABLED` on API traffic, and enables
[OPTIONS pattern hints (client-side)](#options-pattern-hints-client-side).

```python
from ansible_base.lib.serializers.mixins import CleanTextMixin
from rest_framework import serializers

class MyModelSerializer(CleanTextMixin, serializers.ModelSerializer):
    class Meta:
        model = MyModel
        fields = '__all__'
```

Place `CleanTextMixin` **before** `ModelSerializer` in the class list so its
`validate()` runs in the expected MRO order.

### Grandfather behavior

**Goal:** avoid blocking PATCH/PUT on legacy records when only unrelated fields
change.

On **update**, if a submitted text or JSON string equals the stored value (with
DRF whitespace trimming rules for Char/Text fields), validation is skipped for
that value. On **create**, all submitted text fields are checked. Partial
updates validate only keys present in the body.

### OPTIONS pattern hints (client-side)

Client metadata: optional tier 1/tier 2 pattern hints on DRF `OPTIONS` when
enforcement is on.

**What.** For API views whose serializer subclasses `CleanTextMixin`, DRF
`OPTIONS` responses can include extra metadata on `CharField` / `TextField`
serializer fields: `pattern`, `patternDescription`, `flags`, and (tier 1 only)
`normalize`. UIs use these for early feedback before submit.

**Why.** Same tier 1/tier 2 rules as the server, exposed to clients without
hard-coding regex in each app. Patterns are **best-effort** (especially tier 2);
`validate_resource_name` and `validate_free_text` remain the enforcement
boundary—see comments on `build_tier2_frontend_pattern()` in
`ansible_base.lib.metadata`.

**How.** When `ENHANCED_INPUT_VALIDATION_ENABLED` is on, `CleanTextMetadata`
(typically `REST_FRAMEWORK['DEFAULT_METADATA_CLASS']` from DAB settings) calls
`inject_clean_text_patterns()` for each field on a `CleanTextMixin` serializer.
Model field validators do not emit OPTIONS metadata. OpenAPI may also document
pattern fields via `ansible_base.lib.schemas.clean_text_patterns` and
Spectacular postprocessing hooks—same intent, different surface.

### Customization

Extension: which model fields and JSON sub-keys the mixin validates or skips.

Class attributes on the serializer (names are generic; a future refactor may
move or prefix them):

- `name_fields` — tier 1 field names (extend with `DEFAULT_NAME_FIELDS | {...}`).
- `excluded_fields` — skip tier 1/2 entirely (including whole `JSONField`s).
- `excluded_json_keys` — map of JSONField name → frozenset of sub-keys to skip
  at any nesting depth.

DAB ships additional exclusions for authenticators in
`ansible_base.authentication` (for example `AuthenticatorSerializer.excluded_json_keys`
and `AuthenticatorMapSerializer` expansion handling). See those modules when
changing authenticator plugins—not this document.

### Errors

Error shape: how validation failures are returned on API requests.

Multiple field failures are aggregated into one `ValidationError` keyed by
serializer field names. Nested JSON errors use sub-keys under the JSONField name
(see tests in `test_app/tests/lib/serializers/test_clean_text_mixin.py`).

## Model-level validation (guidance)

See [Choosing the validation layer](#choosing-the-validation-layer) for
existing vs new models. This section is optional guidance when
`validate_resource_name` / `validate_free_text` on model fields should also cover
non-DRF paths (management commands, imports, or `save()` after `full_clean()`).
Do not treat model validators as a required DAB pattern.

The tier functions *can* be wired as Django `Field.validators` on
`CharField` / `TextField` columns, for example:

```python
from django.db import models
from ansible_base.lib.utils.validation import validate_resource_name, validate_free_text

class MyNewModel(models.Model):
    name = models.CharField(max_length=512, validators=[validate_resource_name])
    description = models.TextField(default='', validators=[validate_free_text])
```

**Implementation considerations** (not an exhaustive list):

- **Enforcement toggle.** Field validators always raise; log-vs-reject for
  [Enforcement toggle](#enforcement-toggle-enhanced_input_validation_enabled) is
  mixin-only. No toggle-aware model wrappers ship in DAB today.
- **OPTIONS.** No pattern metadata from model validators; use
  [Serializer-level validation](#serializer-level-validation) (mixin) for OPTIONS.
- **Mixin plus model validators on the same fields.** `ModelSerializer` may run
  both field validators and the mixin on the same Char/Text value—DAB does not
  deduplicate (see toggle caveat above).
- **Grandfathering and JSONField.** [Grandfather behavior](#grandfather-behavior)
  and nested `JSONField` checks are mixin-only; validators run only where
  Django/DRF invokes them ([Known limitations](#known-limitations)).

## Known limitations

These apply to the **serializer-level validation DAB ships and tests** today
(`CleanTextMixin` on DRF serializers), not to optional model-level guidance
above. See [Choosing the validation layer](#choosing-the-validation-layer) for
when to use the mixin vs model field validators.

- **Serializer-path only.** The mixin runs in the serializer `validate()`
  method. ORM `create()` / `save()`, management commands, and imports do not
  run it unless those paths go through a serializer that includes the mixin (or
  you add another validation layer yourself).
- **Grandfathering is serializer-only.** On update, unchanged field values are
  skipped even if they would fail today's rules. Django field validators do not
  get old-vs-new context unless you add instance-aware logic in `Model.clean()`.
- **Field discovery caveats.** The mixin validates model columns whose
  `get_internal_type()` is `CharField` or `TextField`. `SlugField` and
  `GenericIPAddressField` are skipped; `URLField` is not (it still reports
  `CharField`). See `_classify_fields()` in `mixins.py`.
- **JSON depth cap.** String values inside `JSONField` data are validated with
  tier 2, recursively up to depth 10. Deeper nesting is not scanned; when
  `ENHANCED_INPUT_VALIDATION_ENABLED` is true, the API returns a generic
  incomplete-validation error for that branch (see `_MAX_JSON_DEPTH` in
  `mixins.py`).
- **Defense in depth.** Server-side input validation does not replace output
  encoding, CSP, or other controls.

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
