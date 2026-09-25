# ORM validation bypass observability

How **django-ansible-base (DAB)** helps applications **detect and log** database
writes that skip `CleanTextMixin` serializer validation. Related:
[CleanTextMixin and validators](validation.md).

## Who should read this

| Reader | Start here |
|--------|------------|
| **DAB maintainer** | [Implementation reference](#implementation-reference-dab-maintainers), [Module reference](#module-reference), [Detection behavior](#how-detection-works) |
| **Application developer** (AWX, EDA, Gateway, Hub, or any DAB consumer) | [Integration checklist](#integration-checklist-for-dab-consumers), [Cookbooks](#cookbooks) |
| **Security / operations** | [What to monitor](#monitoring-and-log-format), [Remediation](#when-a-log-line-appears) |
| **Platform security sign-off** (import/sync coverage) | [Platform triage reference](validation_bypass_platform_triage.md) |

## Problem in one paragraph

`CleanTextMixin` validates Tier 1 / Tier 2 text on **DRF serializers**. Code that
calls `Model.objects.create()`, `instance.save()`, `bulk_create()`,
`bulk_update()`, or `QuerySet.update()` **does not** run those serializers.
DAB adds **observability**: the same validation rules run at selected points and
emit **WARNING** logs (`ORM bypass (…):`). Writes are **never blocked** on these
paths. API enforcement is unchanged (`ENHANCED_INPUT_VALIDATION_ENABLED` on
serializers).

### Which models get ORM bypass checks?

DAB maintains an in-process list of Django models to watch (`_protected_models`,
the **registry**). A model is on that list only if the running app has already
imported a DRF serializer that uses `CleanTextMixin` and points at that model
via `Meta.model`. Import your API serializers in `AppConfig.ready()` so the list
is populated before traffic (see [checklist](#integration-checklist-for-dab-consumers)).

If a model is **not** on the list, the `post_save` handler and the bulk/queryset
audit helpers **exit immediately** — no Tier 1/2 scan and no log. That means
**no coverage** for that ORM path, not that the write was reviewed or approved.

## What DAB ships (automatically)

After you complete the [integration checklist](#integration-checklist-for-dab-consumers):

| ORM path | Covered by DAB without extra call sites? |
|----------|------------------------------------------|
| `.save()` / `.create()` on registered models | **Yes** — `post_save` handler `validation_bypass_logger` |
| `serializer.save()` / `create()` / `update()` on `CleanTextMixin` | **No bypass log** — context flag suppresses false `post_save` lines |
| `bulk_create()` / `bulk_update()` | **No** — Django does not fire `post_save`; you must call [audit helpers](#audit-helpers-bulk-and-queryset) at call sites |
| `QuerySet.update()` | **No** — use `audited_queryset_update` at call sites |

DAB does **not** monkeypatch `QuerySet` or all `bulk_*` globally. Each
application adds **audit call sites** where import/sync/user bulk paths persist
registered text outside serializers (see platform triage guide).

### In scope vs out of scope (this feature)

| In scope | Out of scope |
|----------|----------------|
| Log Tier 1/Tier 2 violations on registered Char/Text (minus `excluded_fields`) | Block ORM writes when validation fails |
| Reuse `validate_resource_name` / `validate_free_text` | Move enforcement to `Model.save()` / `full_clean()` |
| Optional bulk/queryset audit helpers | Global monkeypatch of Django ORM |
| Caller attribution in logs (`[caller: …]`) | Full platform coverage without per-app wiring |

## Integration checklist for DAB consumers

Do this in your Django app’s `AppConfig.ready()` (or rely on
`ansible_base.observability` in `INSTALLED_APPS`, which calls
`register_validation_signals()` for you).

1. **Register the signal** — `register_validation_signals()` (or include
   `ansible_base.observability` in `INSTALLED_APPS`).
2. **Load serializers** — `import your_app.api.serializers` (and any DAB API
   serializers you expose) so `CleanTextMixin` registers models before traffic.
3. **Caller prefixes** — `extend_caller_allowlist_prefixes()` for views, tasks,
   management commands; `extend_internal_caller_prefixes()` for models/signals
   plumbing so `[caller: …]` points at product code.
4. **Bulk / import paths** — Before `bulk_create` / `bulk_update` that persist
   registered text from sync or user bulk APIs, call `audit_bulk_model_instances`
   (or `audit_bulk_item_dicts`). Wrap custom `Serializer.create()` that bulk-writes
   after `is_valid()` in `serializer_mediated_persistence_context` when needed
   (see [bulk dedupe](#audit-helpers-bulk-and-queryset)).
5. **`QuerySet.update()`** — Where product code updates registered text columns with
   literal strings, use `audited_queryset_update` immediately before or instead of
   raw `update()`.

Until steps 4–5 are done for a given ingress path, that path remains a **blind
spot** even if step 1–3 are complete.

## Cookbooks

### I added a CharField to a model exposed on the API

1. Add or extend a **`CleanTextMixin` serializer** for that model (see
   [validation.md](validation.md)).
2. Ensure that serializer module is **imported at startup** (step 2 above).
3. **No DAB change required** — `.save()` on that model is now in the registry.
4. If the field is legitimately free-form (templates, YAML), add it to
   `excluded_fields` on the serializer (affects API validation **and** ORM bypass
   scope for that model).

### My code calls `instance.save()` or `objects.create()` (no serializer)

- If the model is registered: violations log as
  `ORM bypass (post_save): …` and the row is still saved.
- Fix: route user-facing data through a serializer, or accept documented internal
  bypass.

### My code calls `bulk_create()` or `bulk_update()`

1. Confirm the model is registered and the operation touches Char/Text (for
   `bulk_update`, check `fields=`).
2. Immediately before the ORM bulk call:

```python
from ansible_base.lib.utils.bulk_validation_audit import audit_bulk_model_instances

audit_bulk_model_instances(instances, operation="bulk_create")
MyModel.objects.bulk_create(instances)
```

3. For `bulk_update`, pass `update_fields=` so only written columns are scanned.

### My code calls `QuerySet.update(description=...)`

```python
from ansible_base.lib.utils.bulk_validation_audit import audited_queryset_update

audited_queryset_update(
    MyModel.objects.filter(pk=pk),
    description=user_supplied,
)
```

Only **literal string** kwargs are audited; `F()` / `Case` are skipped.

### I want to detect bypasses in production

Search logs for: `ORM bypass (` — subtypes `(post_save)`, `(bulk_create)`,
`(bulk_update)`, `(queryset_update)`. Use `[caller: module:line]` for triage.
Alerting on sustained volume is an application/ops concern.

## How detection works

### Serializer path vs ORM path

| Mechanism | When | Blocks? |
|-----------|------|---------|
| `CleanTextMixin.validate()` | API `is_valid()` | Only if `ENHANCED_INPUT_VALIDATION_ENABLED` |
| `validation_bypass_logger` | Registered model saved outside mixin persistence | **Never** |

`CleanTextMixin` sets a **context flag** during `save()`, `create()`, and
`update()` (including `many=True` list serializers) so `post_save` does not
double-log API traffic.

### Detection flow (`post_save`)

1. Skip if model not in registry.
2. Skip if save is serializer-mediated (context flag).
3. Validate Char/Text (minus unioned `excluded_fields`).
4. Log **only on violation** — caller resolution runs only when logging.

Bypass logging is **independent** of `ENHANCED_INPUT_VALIDATION_ENABLED`.

## Audit helpers (bulk and QuerySet)

```python
from ansible_base.lib.utils.bulk_validation_audit import (
    audit_bulk_model_instances,
    audit_bulk_item_dicts,
    audit_queryset_update,
    audited_queryset_update,
)

instances = audit_bulk_model_instances(instances, operation="bulk_create")
audit_bulk_model_instances(instances, operation="bulk_update", update_fields=["description"])
```

**Bulk API after `is_valid()`:** If `validate()` already logged
`Validation rejected` and enforcement is off, wrap persistence in
`serializer_mediated_persistence_context` (from `ansible_base.lib.serializers.mixins`)
so bulk audits do not duplicate the same field in the same request.

```python
from ansible_base.lib.serializers.mixins import serializer_mediated_persistence_context

def create(self, validated_data):
    with serializer_mediated_persistence_context():
        return self._create_bulk(validated_data)
```

`audit_bulk_*` **materializes** iterables before auditing so generators are not
consumed before `bulk_create()`.

Full API examples:

```python
item_dicts = audit_bulk_item_dicts(MyModel, item_dicts, operation="bulk_create")
MyModel.objects.bulk_create([MyModel(**d) for d in item_dicts])

audit_queryset_update(MyModel, {"description": user_supplied})
MyModel.objects.filter(pk=pk).update(description=user_supplied)
```

Log prefixes: `ORM bypass (bulk_create):`, `ORM bypass (bulk_update):`,
`ORM bypass (queryset_update):`. Helpers **log only**; they do not block writes.

## Implementation reference (DAB maintainers)

This section documents **why** the library is shaped this way and how the pieces
fit together. Application developers can stop at the [cookbooks](#cookbooks);
maintainers and advanced integrators use this when changing DAB or designing
service-wide wrappers.

### Why `post_save` is not enough

| Django API | `post_save` fires? | DAB coverage |
|------------|-------------------|--------------|
| `.save()` / `.create()` | Yes | `validation_bypass_logger` |
| `bulk_create()` / `bulk_update()` | **No** | `audit_bulk_*` at call sites |
| `QuerySet.update()` | **No** | `audit_queryset_update` / `audited_queryset_update` |

Django never emits instance signals for bulk or queryset SQL. A single global
`post_save` handler cannot observe those paths. Product Security import/sync
requirements therefore need **explicit audit call sites** at triaged ingress
points, not only installing DAB.

### Why opt-in helpers instead of monkeypatching ORM

**Rejected approach:** patch `QuerySet.update` or `bulk_create` platform-wide.

| Concern | Why opt-in wins |
|---------|-----------------|
| Blast radius | Hub/Pulp, `django-lifecycle`, third-party libs, and Django upgrades behave differently per service |
| Field scope | `bulk_update` must respect `fields=` — auditing every CharField on an in-memory instance when only JSON changed creates noise |
| Registry scope | Helpers no-op when the model is not in `_protected_models` — a global patch would still run logic on every bulk call |

DAB ships **shared validators + log format** in `bulk_validation_audit.py`; each
service chooses choke points (shared `bulk_update` helper, bulk API `create()`,
SCM import `update()`, etc.). See [platform triage](validation_bypass_platform_triage.md).

### Bulk audit helpers — design

**Functions:** `audit_bulk_model_instances`, `audit_bulk_item_dicts`.

- Reuse `_protected_models`, `_get_text_fields`, and `_validate_field` from
  `validation_signals` so rules match `CleanTextMixin` and `post_save`.
- **`update_fields=`** (bulk_update): only audit columns actually listed in the
  ORM `fields=` argument — avoids deferred-field queries and false positives when
  unrelated text on the instance was changed in memory only.
- **Materialize** the input iterable before the audit loop; return the list so
  callers can pass a generator and still call `bulk_create(materialized)`.
- **Caller resolution is lazy:** `_get_caller_info()` runs on the first violation
  in a batch (shared `caller_info` per helper invocation), not per instance.

**Pseudo-fields:** Some models store prompt-like text outside normal columns
(for example workflow `char_prompts`). The mixin registry may not see those as
`CharField`s; services add small wrappers that `getattr` and validate before
`bulk_create` (documented in consumer PRs, not in DAB core).

### QuerySet audit helpers — design

**Functions:** `audit_queryset_update(model, kwargs)` and
`audited_queryset_update(queryset, **kwargs)`.

- Same registry and validators as bulk helpers.
- Only **literal `str`** values in `update()` kwargs are checked. **`F()`**,
  **`Case`**, and subqueries are skipped — SQL does not expose final row text
  without an extra `SELECT`, and false positives would dominate.
- Typical production use: SCM sync writes cached YAML/text via
  `QuerySet.update(rulebook_rulesets=…)` where no serializer runs on that SQL
  batch.

### Caller attribution (hybrid, lazy)

Logs include `[caller: module.function:line]` **only when a violation is logged**
(not on every save). Resolution walks the stack outward from the audit site:

| Phase | Source | Behavior |
|-------|--------|----------|
| **1 — Allowlist** | `CALLER_INFO_APP_MODULES` setting + `extend_caller_allowlist_prefixes()` | First frame whose `__name__` starts with a registered prefix wins |
| **2 — Denylist skip** | DAB defaults (`django.db.models`, `django.dispatch`, `validation_signals`, `ansible_base.lib.abstract_models`, …) + `extend_internal_caller_prefixes()` | Skip framework / model-wrapper frames; first non-denied frame wins |
| **3 — Fallback** | Skip `django.*`, signal module, `bulk_validation_audit` | First remaining frame, else `"unknown"` |

DAB cannot hardcode AWX/EDA/Hub/Gateway module trees. **Caller quality depends on
narrow allowlists** (views, tasks, management) and **denylisting** internal
`models` / `signals` / sync helpers so logs point at product ingress, not
plumbing.

Implementation uses `inspect` frame walk (`_iter_caller_frames`) and
`f_globals['__name__']` — not `inspect.stack()` on every clean save.

### Registry (`_protected_models`)

**What gets stored:** For each registered model, DAB remembers which text columns
use Tier 1 (name) vs Tier 2 rules and which columns serializers skip via
`excluded_fields`.

**When entries are added:**

- When a `CleanTextMixin` serializer class is defined, its `Meta.model` and
  static `name_fields` / `excluded_fields` are recorded.
- When that serializer is **instantiated**, registration runs again so dynamic
  exclusions (for example `@cached_property excluded_fields`) are merged in.
- If several serializers target the same model, their `name_fields` and
  `excluded_fields` are **combined** (union).

**Why it matters:** The signal and bulk helpers look up the model in this dict
first. Unknown models are ignored so unrelated saves (for example side effects on
models without `CleanTextMixin`) do not produce false positives.

### Serializer path vs ORM path (detailed)

| Logger / message | Trigger | Blocks? |
|------------------|---------|---------|
| `Validation rejected …` (mixin) | `CleanTextMixin.validate()` during `is_valid()` | Only if `ENHANCED_INPUT_VALIDATION_ENABLED` |
| `ORM bypass (post_save):` | `post_save` on registered model, no persistence context | Never |
| `ORM bypass (bulk_*):` / `(queryset_update):` | Audit helpers before bulk/update SQL | Never |

**Context var** `_serializer_validation_active` is set for the duration of
`CleanTextMixin.save()`, `create()`, and `update()` (including **`many=True`**
list serializers, which call child `create()` / `update()` without child
`save()`).

**Grandfathering:** API updates skip unchanged text in `validate()`; mixin
persistence sets the context var so `post_save` does not re-audit that write.
**ORM-direct** saves validate **current** instance values — no grandfathering
(intentional for bypass auditing).

### Deduping `Validation rejected` vs `ORM bypass (bulk_*)`

When enforcement is **off**, `validate()` may log `Validation rejected` and still
persist via bulk ORM. Without dedupe, the same field would log again as
`ORM bypass (bulk_create):`.

| Situation | `ORM bypass` emitted? |
|-----------|----------------------|
| Shell/task `audit_bulk_*` only | **Yes** when text fails |
| After `is_valid()`, bulk write **outside** persistence context | **Yes** (duplicate with enforcement off) |
| Rejection recorded **and** `_serializer_validation_active` during audit | **No** for that `(resource_type, field_name)` |

The rejection registry **alone** does not suppress bulk logs (avoids stale
registry suppressing unrelated audits in workers/tests). **Both** registry entry
**and** active serializer persistence context are required.

Custom bulk `Serializer.create()` after `is_valid()` should use
`serializer_mediated_persistence_context()` (clears rejection registry in
`finally`).

### Performance and blast radius

- `post_save` runs for every model save; unregistered models pay a dict lookup and return.
- Validation + caller walk run only for **registered** models when the save was **not** serializer-mediated, and only log when a field fails.
- Load-test hot paths that `.save()` registered models at high volume before relying on production logs.

### Enforcement toggle independence

`ENHANCED_INPUT_VALIDATION_ENABLED` controls whether the **API** raises on
serializer validation failures. **ORM bypass logging is not gated on that flag**
— observability remains when enforcement is off (common during rollout).

## Module reference

| Module | Role |
|--------|------|
| `ansible_base.lib.utils.validation_signals` | `register_validation_signals()`, `validation_bypass_logger`, registry, caller `extend_*` APIs |
| `ansible_base.lib.utils.bulk_validation_audit` | `audit_bulk_*`, `audited_queryset_update` |
| `ansible_base.lib.serializers.mixins.CleanTextMixin` | API validation + registry + persistence context |
| `ansible_base.observability.apps` | Optional: add `ansible_base.observability` to `INSTALLED_APPS` to register signals |

## Monitoring and log format

```
WARNING … ORM bypass (post_save): validation rejected 'description' on myapp.Organization (violates Tier 2) [caller: myapp.tasks.sync:42]: …
```

Field values are not logged. Caller quality depends on allowlist/denylist
configuration in the host application.

## When a log line appears

1. Use `[caller: …]` to find the write site.
2. Decide if data is trusted (config/sync) vs user-controlled.
3. Prefer fixing ingress (serializer) or upstream data; document intentional bypass.
4. For intentional internal writes, `excluded_fields` on serializers reduces ORM
   bypass scope (union across serializers for the same model).

## Limitations

- No automatic coverage for `bulk_*` or `QuerySet.update()` without audit call sites.
- Only registered models; only Char/Text per mixin rules.
- `audited_queryset_update` does not inspect `F()`-based SQL updates.
- Caller attribution is best-effort, not a full stack trace.

## See also

- [validation.md](validation.md) — tiers, grandfathering, enforcement toggle
- [validation_bypass_platform_triage.md](validation_bypass_platform_triage.md) — import/sync coverage, inventories, sign-off context
- Source: `ansible_base/lib/utils/validation_signals.py`,
  `ansible_base/lib/utils/bulk_validation_audit.py`,
  `ansible_base/lib/serializers/mixins.py`
