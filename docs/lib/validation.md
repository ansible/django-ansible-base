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

## Enforcement toggle — `ENHANCED_INPUT_VALIDATION_ENABLED`

Whether invalid API input is **rejected** or only **logged** is controlled by
the Django setting `ENHANCED_INPUT_VALIDATION_ENABLED` (default `False` when
unset). Consuming applications set it in Django settings. DAB reads the effective
value with `ansible_base.lib.utils.settings.get_setting()`. When
`ANSIBLE_BASE_SETTINGS_FUNCTION` is configured, its return value is used as-is
(including `None`); otherwise DAB uses the Django setting, then the default.

The table below applies only to violations detected by `CleanTextMixin` on API
serializers (not to model field validators or other validation layers).

| Value | Behavior |
|-------|----------|
| `False` (default) | Mixin checks run; violations are logged at WARNING; the request is not rejected for mixin findings. |
| `True` | Same mixin checks; mixin findings raise `ValidationError`. |

When enforcement is off, logs still record violations so operators can see what
would be rejected before turning enforcement on.

This is a Django setting, not a DAB feature flag (`ansible_base.feature_flags`).

`validate_resource_name` and `validate_free_text` always raise when they detect a
violation. Only `CleanTextMixin` applies the log-vs-reject policy above on API
traffic. See [Model-level validation (guidance)](#model-level-validation-guidance)
for how that differs from model field validators.

## Serializer-level validation

DAB applies tier 1/tier 2 on API traffic through `CleanTextMixin` on DRF
serializers—that is what DAB ships and tests on existing models.

`CleanTextMixin` in `ansible_base.lib.serializers.mixins` applies the tiers
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

`CleanTextMixin` gives you API write enforcement (above) and also advertises
the same tier 1/tier 2 rules in a structured form on DRF
`OPTIONS` responses (`pattern`, `patternDescription`, `flags`, and tier 1
`normalize` on Char/Text fields). Clients that issue `OPTIONS` requests—including
platform UIs—can use that metadata for client-side validation before submit.
`validate_resource_name` and `validate_free_text` remain the server enforcement
boundary; OPTIONS patterns are best-effort (especially tier 2).

OPTIONS hints appear when all of the following hold:

1. The view’s serializer subclasses `CleanTextMixin`.
2. The Django setting `ENHANCED_INPUT_VALIDATION_ENABLED` is `True`.
3. DRF metadata is `ansible_base.lib.metadata.CleanTextMetadata` (DAB’s default
   `REST_FRAMEWORK['DEFAULT_METADATA_CLASS']`; a custom metadata class skips injection).
4. The serializer field maps to a model `CharField` or `TextField` that is not in
   `excluded_fields`.

Model field validators do not emit OPTIONS metadata.

**Exception — AuthenticatorMap trigger fields.** The attribute names and values
under the `triggers` `JSONField` are enforced server-side (tier 2) but, being
nested JSON rather than Char/Text model fields, get no OPTIONS hint from the rules
above. `AuthenticatorMapViewSet` uses a custom
`AuthenticatorMapMetadata(CleanTextMetadata)` that injects top-level `attribute`
and `value` hints into the **create (`POST`) action only** when
`ENHANCED_INPUT_VALIDATION_ENABLED` is on. The platform UI resolves nested form
fields (`attributes.{index}.attribute`, `attributes.{index}.value`) by their last
path segment, so these drive client-side validation with no UI change. Update
(`PUT`) is intentionally excluded because the serializer
[grandfathers](#grandfather-behavior) stored attribute names on update — a static
OPTIONS pattern can't express that per-instance exception, so injecting it there
would wrongly block edits to maps carrying a legacy name (new names entered during
an edit are still enforced server-side).

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

When enforcement raises, multiple failures are aggregated into one
`ValidationError`. Text field errors use serializer field names (including when
`source=` renames the attribute). JSON errors use the **model** JSON column name
as the top-level key, with nested paths beneath it—even if the serializer field
is renamed (see tests in `test_app/tests/lib/serializers/test_clean_text_mixin.py`).

## Model-level validation (guidance)

The validators behind `CleanTextMixin` (`validate_resource_name`,
`validate_free_text`) can also be attached directly to model `CharField` /
`TextField` columns. That is optional guidance—not a required DAB pattern—when
the same rules must run on non-DRF paths (management commands, imports, or
`save()` after `full_clean()`). Tradeoffs (toggle, OPTIONS, grandfathering,
duplicate checks with the mixin) are below.

The tier functions *can* be wired as Django `Field.validators` on
`CharField` / `TextField` columns, for example:

```python
from django.db import models
from ansible_base.lib.utils.validation import validate_resource_name, validate_free_text

class MyNewModel(models.Model):
    name = models.CharField(max_length=512, validators=[validate_resource_name])
    description = models.TextField(default='', validators=[validate_free_text])
```

Those functions raise `rest_framework.serializers.ValidationError`, which DRF
field validation accepts when the API uses a `ModelSerializer`. For
`Model.full_clean()` or other Django ORM paths, wrap them or convert to
`django.core.exceptions.ValidationError`.

**Implementation considerations** (not an exhaustive list):

- **Enforcement toggle.** Field validators always raise; log-vs-reject for
  [Enforcement toggle](#enforcement-toggle--enhanced_input_validation_enabled) is
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
above.

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
- **JSON depth cap.** String leaves inside `JSONField` data are validated with
  tier 2 when traversal reaches them (including a string at depth 10). The cap
  applies when **entering** a nested `dict` or `list`: at depth 10 and deeper,
  that container and its descendants are not scanned; when
  `ENHANCED_INPUT_VALIDATION_ENABLED` is true, the API returns a generic
  incomplete-validation error for that branch (see `_MAX_JSON_DEPTH` in
  `mixins.py` and `test_value_at_max_json_depth_is_validated`).
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
