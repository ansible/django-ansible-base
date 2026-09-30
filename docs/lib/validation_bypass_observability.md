# ORM validation bypass observability

DAB **logs** (does not block) Tier 1 / Tier 2 text violations when registered models
are written outside `CleanTextMixin` serializers. Same rules as
[validation.md](validation.md). Import/sync triage and sign-off inventories live in
[validation_bypass_platform_triage.md](validation_bypass_platform_triage.md).

**Audience:** DAB **consumers** wire signals, serializers, caller prefixes, and
audit call sites. **Security / ops** search logs for `ORM bypass (`.

## What DAB does vs what you wire

| ORM path | Automatic after checklist steps 1–3? |
|----------|--------------------------------------|
| `.save()` / `.create()` on registered models | **Yes** — `post_save` → `validation_bypass_logger` |
| `CleanTextMixin` `save()` / `create()` / `update()` | **No bypass log** — persistence context suppresses false `post_save` lines |
| `bulk_create()` / `bulk_update()` | **No** — call `audit_bulk_*` at the call site |
| `QuerySet.update()` | **No** — use `audited_queryset_update` for literal string kwargs |

DAB does **not** monkeypatch bulk or `QuerySet` globally. Logs are **WARNING** only;
API blocking stays on serializers and `ENHANCED_INPUT_VALIDATION_ENABLED`.
ORM bypass logging is **not** gated on that flag.

**Registry:** `_protected_models` lists models that have a loaded `CleanTextMixin`
serializer (`Meta.model`). Unregistered models are ignored (fast no-op) — that is
**no coverage**, not approval of the write. Import serializers in `AppConfig.ready()`.

## Integration checklist

In `AppConfig.ready()` (or add `ansible_base.observability` to `INSTALLED_APPS`,
which calls `register_validation_signals()`):

1. **Register signals** — `register_validation_signals()` if not using observability app.
2. **Load serializers** — `import your_app.api.serializers` so models register before traffic.
3. **Caller prefixes** — `extend_caller_allowlist_prefixes()` (views, tasks, management);
   `extend_internal_caller_prefixes()` (models, signals, internal helpers) so
   `[caller: …]` points at product code.
4. **Bulk paths** — For custom bulk `Serializer.create()` / `update()` after
   `is_valid()`, use `input_validation_auditor` (see below). For tasks, sync, and
   other non-serializer ingress, call `audit_bulk_model_instances` or
   `audit_bulk_item_dicts` before the ORM write.
5. **`QuerySet.update()`** — Use `audited_queryset_update` for literal string columns;
   `F()` / `Case` are skipped.

Steps 4–5 are still blind spots until wired for that ingress path.

**Example `AppConfig.ready()`** (skip `register_validation_signals()` if
`ansible_base.observability` is already in `INSTALLED_APPS`):

```python
def ready(self):
    from ansible_base.lib.utils.validation_signals import (
        register_validation_signals,
        extend_caller_allowlist_prefixes,
        extend_internal_caller_prefixes,
    )

    register_validation_signals()
    import myapp.api.serializers  # noqa: F401 — registers CleanTextMixin models

    extend_caller_allowlist_prefixes(
        ["myapp.api.views", "myapp.api.serializers", "myapp.tasks"]
    )
    extend_internal_caller_prefixes(["myapp.models", "myapp.signals"])
```

## Common tasks

**New CharField on an API model:** Add `CleanTextMixin` on the serializer, import it
at startup, add `excluded_fields` only for secrets/templates/YAML (affects API
validation and ORM scope). No DAB library change.

**Direct `instance.save()` or `objects.create()` (no serializer):** If the model is
registered, bad Tier 1/2 text logs as `ORM bypass (post_save):` and the row is still
saved. Prefer routing user-controlled data through a serializer, or document
intentional internal bypass.

**`bulk_create` / `bulk_update` (tasks, sync, management — not serializer APIs):**

```python
from ansible_base.lib.utils.bulk_validation_audit import audit_bulk_model_instances

instances = audit_bulk_model_instances(instances, operation="bulk_create")
MyModel.objects.bulk_create(instances)

instances = audit_bulk_model_instances(
    instances, operation="bulk_update", update_fields=["description"]
)
MyModel.objects.bulk_update(instances, fields=["description"])
```

Pass `update_fields=` for `bulk_update` so only columns in the ORM `fields=` list are
audited. Helpers **materialize** iterables (including generators) and return a list —
reuse that return value for `bulk_create` / `bulk_update`.

**`QuerySet.update()`:**

```python
from ansible_base.lib.utils.bulk_validation_audit import audited_queryset_update

audited_queryset_update(MyModel.objects.filter(pk=pk), description=value)
```

**Bulk API after `is_valid()`:**

```python
from ansible_base.lib.utils.bulk_validation_audit import input_validation_auditor

def create(self, validated_data):
    rows = build_rows(validated_data)
    with input_validation_auditor(MyModel) as m:
        m.objects.bulk_create(rows)
```

`input_validation_auditor` applies serializer persistence context (dedupe against
`Validation rejected` when enforcement is off) and audits the matching bulk operation.
Only `bulk_create` and `bulk_update` on ``m.objects`` are wrapped — not arbitrary
queryset methods.

**Advanced:** `serializer_mediated_persistence_context()` plus `audit_bulk_*` remains
valid when you audit before a non-standard ORM call (for example custom pseudo-fields).

**Detect bypasses in production:** Search `ORM bypass (` (logger
`ansible_base.lib.utils.validation_signals`, level WARNING). Distinct from API
`Validation rejected` (`ansible_base.lib.serializers.mixins`). Values are not logged;
use `[caller: module.function:line]` to find the write site. That label comes from
a stack walk (`_get_caller_info()`): prefer frames under `CALLER_INFO_APP_MODULES`
and `extend_caller_allowlist_prefixes()`, then skip internal denylist modules.

## Registry and dynamic serializer configuration

`CleanTextMixin` registers `name_fields` and `excluded_fields` at **class**
definition (`__init_subclass__`) and again on each serializer **instance**
(`__init__`) so dynamic config (for example `@cached_property excluded_fields`)
merges into the registry.

Multiple serializers for the same model **union** `name_fields` and
`excluded_fields`. If any serializer excludes a column, ORM bypass helpers and
`post_save` **do not** scan that column.

### `excluded_fields` union policy

**Contract:** Union across all `CleanTextMixin` serializers for a model (class +
instance registration). Exclusions mean the column is **not** simple Tier 1/2 free
text for observability (secrets, credential blobs, Jinja/YAML/JSON payloads) — not
“this endpoint skipped validation.”

**Why union (not intersection):** Intersection would force every serializer to
agree before excluding a column from ORM audit, re-scanning `password`, `extra_vars`,
`variables`, `inputs`, etc. on sync/task paths and drowning signal in noise.

**Component review:** Controller, EDA, Gateway, and Hub CleanTextMixin usage was
checked for mixed-serializer conflicts (one serializer excluding normal user text
another validates on the same model). Exclusions cluster on secrets/structured blobs;
no production case found where `description`-class fields conflict. **Tradeoff:**
union can false-negative if a new serializer excludes a column others treat as free
text — keep exclusions narrow; see `TestExcludedFieldsUnionPolicy` in
`test_validation_signals.py`.

## Serializer persistence suppression

`_serializer_validation_active` is set for all of `CleanTextMixin.save()`,
`create()`, and `update()` (including `many=True` child `create()` / `update()`).
While active, `post_save` bypass logging is skipped for **every** registered model
in that process — intentional so validated API writes are not double-logged
(enforcement off, grandfathering).

`serializer_mediated_persistence_context()` sets the **same global flag** for custom
bulk `create()` / `update()` after `is_valid()`; it is not per-model or per-field.

| Mechanical gap | Mitigation |
|----------------|------------|
| `serializer.save(**kwargs)` with text kwargs that never ran through `validate()` | Put user text in `validated_data` / `is_valid()`. |
| Nested `.save()` / `.create()` on another registered model inside the context | Finish `super().create()` / `super().update()` first, use another serializer, or `audit_bulk_*` before bulk ORM. |

Observability targets **non-serializer** ingress; field-scoped suppression is out of
scope for this library unless product requirements change.

## `post_save` behavior

1. Skip unregistered models.
2. Skip when serializer persistence context is active.
3. For `update_fields`, only audit listed Char/Text columns (minus unioned exclusions).
4. Log only on violation; resolve caller only when logging.

**Grandfathering:** Serializer `validate()` skips unchanged text on update; ORM-direct
saves audit current instance values (no grandfathering).

## Deduping `Validation rejected` vs `ORM bypass (bulk_*)`

When enforcement is off, `validate()` may log `Validation rejected` and still persist
via bulk ORM. Suppress matching `ORM bypass` for `(resource_type, field_name)` only
when **both** the rejection registry entry exists **and**
`_serializer_validation_active` is set during the audit. Registry alone does not
suppress bulk logs (avoids stale registry in workers/tests).

## Caller attribution

On violation only: allowlist (`CALLER_INFO_APP_MODULES`,
`extend_caller_allowlist_prefixes`), then skip denylisted frames
(`extend_internal_caller_prefixes`), then fallback. Uses frame walk, not
`inspect.stack()` on every clean save.

## Module reference

| Module | Role |
|--------|------|
| `ansible_base.lib.utils.validation_signals` | Signals, registry, `extend_*` caller APIs |
| `ansible_base.lib.utils.bulk_validation_audit` | `input_validation_auditor`, `audit_bulk_*`, `audited_queryset_update` |
| `ansible_base.lib.serializers.mixins.CleanTextMixin` | API validation, registry, persistence context |
| `ansible_base.observability.apps` | Optional `INSTALLED_APPS` entry to register signals |

## Limitations

- No `bulk_*` / `QuerySet.update()` coverage without explicit audit call sites.
- Registered models only; Char/Text per mixin rules (minus unioned `excluded_fields`).
- `audited_queryset_update` skips `F()`-based updates.
- Global serializer persistence context; see [above](#serializer-persistence-suppression).
- Caller attribution is best-effort.

## See also

- [validation.md](validation.md) — tiers, enforcement toggle
- [validation_bypass_platform_triage.md](validation_bypass_platform_triage.md) — import/sync hooks, inventories
- Source: `validation_signals.py`, `bulk_validation_audit.py`, `mixins.py`
