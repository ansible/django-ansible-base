# Review: ORM-Direct Validation Bypass Signal (AAP-86051)

## Summary Status

| Finding | Category | Status |
|---------|----------|--------|
| #1: Double-logging guard | Correctness | ✅ FIXED |
| #2: Caller info | Usability | ✅ HYBRID (allowlist → denylist → fallback) in DAB |
| #3: Duplicate log entries | Observability | ✅ FIXED |
| #4: Bulk operations unobservable | Scope | 🟡 DAB helpers shipped; sync/import wiring in services TBD |
| #5a: Enforcement gating | Consistency | ✅ FIXED |
| #5: No model registry | Scope | ✅ FIXED |
| #6: Platform-wide blast radius | Risk | 🟡 PARTIALLY MITIGATED |

**Net result:** The signal is trustworthy for its core function (accurate, non-blocking observability on single-instance ORM bypasses, with serializer-mediated writes suppressed via the context var). Correctness (#1, #3), registry scope (#5), and enforcement/logging consistency (#5a) are fixed. **Caller attribution (#2)** is implemented in DAB as a hybrid allowlist → denylist → fallback walk, with `CALLER_INFO_APP_MODULES`, `extend_caller_allowlist_prefixes()`, and `extend_internal_caller_prefixes()` — **downstream services still must register prefixes** for production-accurate callers. **Bulk (#4):** `post_save` still cannot see bulk APIs; DAB now ships `bulk_validation_audit` helpers; Controller/EDA/Hub/Gateway must call them at sync/import sites. **Performance (#6)** remains a load-test item (expensive work only on registered models and only when the save is not serializer-mediated).

---

## Open Items & Recommendations

### #2: Caller Info Attribution

**DAB (done on branch):** `_get_caller_info()` in `validation_signals.py` uses **hybrid**
resolution — (1) first outward frame matching `CALLER_INFO_APP_MODULES` and/or
`extend_caller_allowlist_prefixes()`, (2) else denylist walk over DAB defaults plus
`extend_internal_caller_prefixes()`, (3) else fallback (first non-`django.*` frame not
in utility modules, else `"unknown"`). Tests: `TestCallerAttribution` (mocked stack +
`CALLER_INFO_APP_MODULES` integration + extend APIs).

**Downstream (still required):** DAB cannot know AWX/EDA/Hub/Gateway module names at
build time. Each service should register **narrow** allowlists (e.g. `awx.main.tasks`,
`awx.api.views`) and/or denylist prefixes for base-model plumbing (e.g.
`awx.main.models`) in `AppConfig.ready()` before relying on `[caller: …]` in production
logs. See [Caller attribution](validation_bypass_paths.md#caller-attribution).

**Residual:** Misconfigured allowlists that are too broad (e.g. entire `awx.main`) can
still stop at the wrong layer; fallback frames may be low-confidence for REPL/tests.

---

### #4: Bulk Operations Coverage

**Current state:** `validation_bypass_logger` still cannot observe bulk APIs (no
`post_save`). DAB adds **`ansible_base.lib.utils.bulk_validation_audit`**
(`audit_bulk_model_instances`, `audit_bulk_item_dicts`) — same registry and validators as
the signal, log prefix `ORM bypass (bulk_create): …`. Unit test:
`TestBulkValidationAudit.test_audit_bulk_model_instances_logs_violation`.

**Available approaches:**

1. **Model-level validators** — ❌ Ruled out (requires version updates across all endpoints).
2. **QuerySet method wrapping:** Monkeypatch in DAB. Pro: automatic. Con: **high blast radius**, Django fragility, library interaction risk.
3. **Hook at sync/import site:** Add validation in the services where bulk writes happen (project sync, inventory source updates, collection imports). Pro: **low blast radius**, targeted. Con: coordinated changes across Controller/EDA/Hub/Gateway, doesn't catch other bulk ops.
4. **Ship with documented gap:** Accept that bulk operations aren't observed by this signal. Pro: ships faster, lowest risk. Con: leaves primary risk unobserved.

**Decision:** **Option 3 (sync/import hooks)** — documented in
[validation_bypass_paths.md](validation_bypass_paths.md) (Bulk Operations + Remediation).
AAP is **not** relying on model-level validators or `save()`/`full_clean()` changes for
this epic; optional `bulk_validation_audit` helpers in DAB reduce boilerplate. Service
PRs add hooks at high-risk bulk sites.

**Implementation approach:** Reuse DAB's existing validators rather than duplicating them:
- Import `validate_resource_name()` and `validate_free_text()` from `ansible_base.lib.utils.validation`
- Call them before `bulk_create()` in each service's sync/import code
- Log violations (don't block the sync, just audit)

Example:
```python
from ansible_base.lib.utils.validation import validate_resource_name, validate_free_text

for item in items_to_sync:
    if 'name' in item:
        try:
            validate_resource_name(item['name'])
        except ValidationError as e:
            logger.warning(f"Invalid name in sync: {e}")
    if 'description' in item:
        try:
            validate_free_text(item['description'])
        except ValidationError as e:
            logger.warning(f"Invalid description in sync: {e}")

MyModel.objects.bulk_create([MyModel(**item) for item in items_to_sync])
```

**Service follow-up:** Add `audit_bulk_*` (or direct validator calls) immediately before
`bulk_create()` / `bulk_update()` at project sync, inventory import, collection import,
and similar paths. AAP is **not** changing model `save()` / `full_clean()` for this epic.

---

## Full Findings

Findings were empirically reproduced by running the branch's own test suite under `TESTAPP_MODE=sqlite` (no Postgres available in this environment) and by scripting two additional scenarios the existing tests don't cover: a fully valid serializer-mediated save, and a grandfathered-field serializer update.

## 1. Double-logging guard does not work for real writes (CONFIRMED — now FIXED, see "Status of fixes" below)

**File:** `ansible_base/lib/serializers/mixins.py:87`

The context var meant to suppress double-logging is only held open for the
duration of `validate()`, which runs during `is_valid()`. The actual
`instance.save()` (and its `post_save` signal) always happens later, in a
separate `serializer.save()` call, after the token has already been reset in
the `finally` block.

**Reproduction:** Created `Organization(name='Legacy<Invalid>Name')` directly
(simulating a pre-existing grandfathered record), then did a normal partial
update through a `CleanTextMixin` serializer changing only `description`.
`is_valid()` correctly grandfathers the unchanged `name` field and returns
`True` — a fully compliant, serializer-mediated write. But `.save()` still
fires the `post_save` signal, which has no concept of grandfathering and
re-validates the raw stored `name` value, logging:

```
ORM bypass: validation rejected 'name' on test_app.Organization (violates Tier 1) [caller: django.db.models.base.save_base:1023]: Enter a valid name...
```

even though this was not a bypass at all. This directly violates AC #4
("Writes that pass through a DRF serializer with CleanTextMixin are NOT
double-logged"). The included test suite never catches this because its one
"no double-logging" test (`test_serializer_write_no_signal_log`) only covers
the case where `is_valid()` returns `False`, so `.save()` is never called and
the assertion trivially passes.

## 2. Caller info resolves to Django internals, not the real caller (CONFIRMED — FIXED in DAB via hybrid walk; downstream registration still required; see "Status of fixes" below)

**File:** `ansible_base/lib/utils/validation_signals.py:60`

`_get_caller_info()`'s hardcoded `skip_frames=3` does not land on the actual
calling code — it resolves to `django.db.models.base.save_base`.

**Reproduction:** Running the included suite under `TESTAPP_MODE=sqlite`,
`test_caller_info_captured` fails:

```
assert 'test_validation_signals' in "ORM bypass: ... [caller: django.db.models.base.save_base:1023]: ..."
```

Every log entry produced in this session, from both plain ORM creates and
serializer-mediated updates, shows the same wrong `save_base` caller. This
makes the audit log's most actionable field (AC #2: "Calling code path")
useless for its stated purpose of letting a security engineer trace back to
the real bypass site.

**Why it's hard to fix:** Each service (AWX, EDA, Hub, Gateway) has its own
`CommonModel.save()` wrapper in its own repo (e.g., `awx.main.models.base`,
`aap_eda.core.models.base`). The frame walk needs to skip those too, but DAB
can't hardcode them — they don't exist in this repo. The current denylist
only knows about `ansible_base.*` modules, so downstream services will
reproduce the same "wrong caller" symptom for their own base models.

**Possible solutions:**

1. **Extend the denylist per-service:** Each service adds its own internal
   module prefixes (`awx.main.models`, `aap_eda.core.models`, etc.) to the
   denylist. Pros: local control, services own their frame layers. Cons:
   requires coordination, maintenance burden spreads across repos, no guarantee
   of completeness as services gain new internal layers.

2. **Whitelist approach instead:** Signal given explicit list of "user
   application" prefixes to *accept* instead of "internal" to skip (e.g.,
   `CALLER_INFO_APP_MODULES = ['awx.main', 'aap_eda.core', ...]`). Pros:
   services explicitly declare their app code, clearer intent. Cons: requires
   explicit configuration per service, adds setup burden.

3. **Heuristic: stop at first non-Django frame:** Walk until you hit something
   that's not `django.*`, assume that's the caller. Pros: simple, no
   configuration. Cons: might stop at first library wrapper (could be wrong
   layer), fragile to library versions.

4. **Heuristic: stop at first frame outside the current repo:** Walk until you
   leave the repo that's currently running (detected via `__file__` or package
   structure). Pros: natural boundary, no config. Cons: complex to implement,
   edge cases with installed packages and pytest fixtures.

**Implementation sketches for options 1 & 2:**

Option 1 (per-service denylist extension):
```python
# In DAB (ansible_base/lib/utils/validation_signals.py)
_INTERNAL_CALLER_PREFIXES = [
    'django.db.models',
    'django.dispatch',
    'ansible_base.lib.utils.validation_signals',
    'ansible_base.lib.abstract_models',
]

def extend_internal_caller_prefixes(prefixes):
    """Called by downstream services to register their internal modules."""
    _INTERNAL_CALLER_PREFIXES.extend(prefixes)

# Then in each service's AppConfig.ready() (e.g., Controller):
from ansible_base.lib.utils.validation_signals import extend_internal_caller_prefixes
extend_internal_caller_prefixes([
    'awx.main.models',
    'awx.main.tasks',
])
```

Option 2 (allowlist — implemented as phase 1 of hybrid, not merged into denylist):
```python
# settings.py (Controller example) — narrow entry points, not whole awx.main
CALLER_INFO_APP_MODULES = [
    'awx.main.tasks',
    'awx.api.views',
    'awx.main.management',
]

# and/or AppConfig.ready():
from ansible_base.lib.utils.validation_signals import extend_caller_allowlist_prefixes
extend_caller_allowlist_prefixes(['awx.main.tasks'])
```

## 3. Duplicate log entries for a single save (CONFIRMED — now FIXED, see "Status of fixes" below)

**File:** `ansible_base/lib/utils/validation_signals.py:120`

A single logical save can emit duplicate log entries for the same field
violation.

**Reproduction:** Under `TESTAPP_MODE=sqlite`, `test_orm_update_tier1_violation_logs`
expects 1 log record after a single `org.save()` with one invalid field, but
gets 2; `test_multiple_field_violations_logged` expects 2 records (one per
violating field) but gets 3. The signal fires more than once per `.save()`
call (likely another `post_save`-connected receiver on `Organization` causing
an internal re-save), and `validation_bypass_logger` has no de-duplication —
inflating downstream audit/alerting volume and making the "one entry per
violation" framing in the doc's Log Format section inaccurate.

## 4. Bulk operations are silently unobservable via post_save (CONFIRMED — signal unchanged; DAB audit helpers + service hooks are the mitigation)

**File:** `docs/lib/validation_bypass_paths.md:341`

The doc lists `bulk_create()` / `bulk_update()` / `QuerySet.update()` as
bypass paths, but `post_save` (the only hook implemented) is never fired by
those APIs, so the signal cannot detect them at all.

**Why this matters:** Project sync / inventory source update / collection
import — the exact examples given under "Bulk Operations" and cited in the
Jira ticket's own Goal as the primary motivating risk — use `bulk_create()`
or `queryset.update()` in practice. These are the highest-risk category (rated
"Medium to High" in the doc) and they have zero observability from this
signal.

**Why post_save can't catch them:** Django by design does not fire signals
(`post_save`, `pre_save`, or any other) for `bulk_create()`, `bulk_update()`,
or `QuerySet.update()` — these are database-level operations, not model
instantiation.

**Possible solutions to close the gap:**

1. **Model-level validators:** ❌ **NOT AN OPTION.** Adding validators directly
   to model fields would require version updates across all AAP endpoints
   (Controller, EDA, Hub, Gateway) and is out of scope for this story.

2. **Wrap QuerySet methods:** Monkeypatch `QuerySet.bulk_create()`,
   `bulk_update()`, and `update()` globally in DAB's `AppConfig.ready()` to
   intercept and validate before writing. Pros: automatic, no caller
   cooperation needed. Cons: **high blast radius** (core ORM methods), fragile
   to Django version changes, risk of silent interaction with other libraries
   that also hook these (e.g., Hub's `django-lifecycle`).

3. **Hook at sync/import site:** Add validation in the specific code paths
   that do bulk writes (project sync, inventory source updates, collection
   imports) in the downstream services themselves, rather than a generic DAB
   mechanism. Pros: targeted, low blast radius on DAB, localized to the
   services that do bulk writes. Cons: not platform-wide, requires coordinated
   changes across Controller/EDA/Hub/Gateway, doesn't catch other bulk
   operations outside those specific paths.

4. **Leave as out-of-scope for now:** Document that bulk operations are not
   observed by this signal, acknowledge the gap, revisit later if needed. Pros:
   ships faster, lower risk, minimal blast radius. Cons: leaves the "primary
   motivating risk" (per the ticket's Goal) unobserved by this story.

**Current state:** Bulk writes remain invisible to `post_save`. **Option 3** is adopted:
`bulk_validation_audit` in DAB plus targeted service call sites (see Open Items §4).
QuerySet monkeypatch (option 2) rejected; model validators (option 1) ruled out for the
serializer/grandfathering approach.

## 5a. Signal is gated on `ENHANCED_INPUT_VALIDATION_ENABLED`, but `CleanTextMixin` itself is not (CONFIRMED — now FIXED, see "Status of fixes" below)

**Files:** `ansible_base/lib/utils/validation_signals.py:141`, `ansible_base/lib/serializers/mixins.py:170`

`validation_bypass_logger` returns early — logging nothing — when
`ENHANCED_INPUT_VALIDATION_ENABLED` is `False`. But `CleanTextMixin._run_text_validator`
calls `self._log_validation_failure(...)` unconditionally in its `except` block;
only the *blocking* behavior (collecting into `errors` and raising when
`enforce` is set) is gated on that setting, not the logging. So today,
serializer-mediated validation failures are already logged with enforcement
off, while ORM-direct bypass writes are not — an inconsistency the setting
gate introduces, not something called for anywhere in AAP-86051's acceptance
criteria.

This also inverts the story's own intent. The signal is explicitly
non-blocking, log-and-alert observability (AC #3), meant to let a security
engineer see how much bypass traffic exists *before* deciding it's safe to
turn enforcement on for a given service. Gating the signal behind the same
flag that turns enforcement on means that visibility only exists after
enforcement is already live — exactly when it's least useful. The fix is to
drop the `ENHANCED_INPUT_VALIDATION_ENABLED` check from `validation_bypass_logger`
entirely, so it logs bypass violations regardless of enforcement state, matching
`CleanTextMixin`'s own logging behavior.

## 5. No registry of protected models — likely false-positive noise once services start wiring in CleanTextMixin (PLAUSIBLE — now FIXED, see "Status of fixes" below)

**File:** `ansible_base/lib/utils/validation_signals.py:141`

`post_save` is connected with no sender filter and no registry of "models
covered by CleanTextMixin in their serializers" (AC #1's literal scope), so
once `ENHANCED_INPUT_VALIDATION_ENABLED` is on, every model save in the
process is checked — including models whose serializers haven't adopted
`CleanTextMixin` yet.

Service Wiring for Controller/EDA/Hub/Gateway (the epics that add
`CleanTextMixin` to those services' serializers) is now well underway, and
complete for some services — so this is not a future-only concern. For any
service that has not yet finished wiring a given serializer, every normal API
write going through that still-unwired serializer would get logged as "ORM
bypass," even though it went through a standard DRF request/serializer path —
because the mechanism can't distinguish "no `CleanTextMixin` serializer
exists yet" from "a real ORM-direct write skipped serializers." Conversely,
for services/models that have already completed wiring, the registry fix
(see the fixed/open status below) is what actually makes the signal usable in
production now, not just a hypothetical safeguard for later.

## 6. Platform-wide blast radius from unscoped registration in a shared library (RISK — PARTIALLY MITIGATED, see "Status of fixes" below)

**Files:** `ansible_base/lib/utils/validation_signals.py`, `ansible_base/observability/apps.py`

DAB is a shared library loaded into every AAP service's own Django process
(Controller, EDA, Hub, Gateway). Anything DAB registers without scoping — an
unfiltered `post_save.connect()` with no `sender`, or (if pursued to close
finding #4) a monkeypatched `QuerySet.bulk_create`/`update` — runs against
every model in every service simultaneously, not just DAB's own models. That
changes the risk profile of this story considerably:

- **Platform-wide simultaneous incidents, not isolated ones.** A bug or
  performance regression ships as one DAB change but can surface as separate
  incidents across all four services at once, and potentially at different
  times depending on each service's independent DAB upgrade cadence — making
  root-causing "weird behavior in EDA" back to a DAB change harder than a
  normal single-service bug.
- **Hot-path performance exposure.** The handler is invoked on every `post_save`,
  but **expensive work** (`inspect.stack()` + per-field regex) runs only for
  **registered** models when the save did **not** go through `CleanTextMixin.save()`
  (context var). Serializer-mediated API writes short-circuit after a dict lookup and
  context-var check. Risk concentrates on **high-frequency registered models** saved
  via ORM (tasks, callbacks) and on growing serializer wiring — not on every row in
  the database. Load-test registered resources before assuming API paths are negligible
  at scale.
- **Monkeypatching core ORM methods (for the bulk-op gap, #4) would raise the
  stakes further.** Django has no official hook for `bulk_create`/`update`,
  so closing that gap likely means overriding `QuerySet` methods process-wide
  — risking silent interaction with other libraries that already hook the
  same methods (e.g. Hub's `django-lifecycle`), and coupling DAB to Django
  internals that can shift across the different Django versions each service
  runs.
- **Already-demonstrated correctness bugs compound the exposure.** Findings
  #1–#3 above (false positives on compliant writes, duplicate log entries,
  useless caller info) show a genuinely broken version of this mechanism was
  about to ship into that exact blast radius, and DAB's own test suite didn't
  catch it. DAB cannot see each downstream service's real save volume or
  concurrency patterns, so DAB-side testing alone can't guarantee no hot-path
  regression in, say, AWX under production job-event volume.
- **Wrong signal is worse than no signal for a security-observability
  feature.** False positives train responders to ignore the log; the bulk-op
  blind spot (#4) means the genuinely risky sync/import paths look clean
  when they're actually just invisible. Either failure mode erodes trust in
  the tool faster than shipping nothing would.

**Recommendation:** keep enforcement behind a default-off setting (already
true via `ENHANCED_INPUT_VALIDATION_ENABLED`), validate under realistic load
in at least one downstream service's staging environment before enabling
broadly, and prefer the narrower registry-based approach (§5) over any global
monkeypatch — the smaller the unscoped surface, the smaller the blast radius
when something is wrong.

## Status of fixes (as of latest unstaged changes on AAP-86051)

Changes on the branch include `ansible_base/lib/serializers/mixins.py`,
`ansible_base/lib/utils/validation_signals.py`, new
`ansible_base/lib/utils/bulk_validation_audit.py`, `docs/lib/validation_bypass_paths.md`,
this review doc, and `test_app/tests/lib/utils/test_validation_signals.py` (expanded
beyond the original 22 tests with `TestCallerAttribution` and `TestBulkValidationAudit`).
Re-verify with:

`TESTAPP_MODE=sqlite python -m pytest test_app/tests/lib/utils/test_validation_signals.py -v`

- **#1 (double-logging guard) — FIXED, verified.** The context var is now set
  and reset around `CleanTextMixin.save()` itself (spanning the actual
  `.save()` call and any synchronous `post_save` cascades it triggers), not
  just `validate()`. New regression tests reproduce both scenarios used to
  prove the original bug (a valid serializer create, and a grandfathered-field
  serializer update) and both pass.
- **#2 (caller info) — IMPLEMENTED in DAB (hybrid); downstream config outstanding.**
  `_get_caller_info()` now runs three phases: allowlist (`CALLER_INFO_APP_MODULES`,
  `extend_caller_allowlist_prefixes()`), denylist (DAB defaults including
  `ansible_base.lib.abstract_models`, plus `extend_internal_caller_prefixes()`),
  then fallback. `test_caller_info_captured` still passes when allowlist is empty
  (denylist-only path). New tests cover allowlist priority, denylist-only path, settings
  integration, and extend APIs. **Production-accurate callers for AWX/EDA/Hub/Gateway
  still require per-service registration** documented in `validation_bypass_paths.md` —
  not verifiable inside DAB's test app alone.
- **#3 (duplicate log entries) — FIXED, verified**, as a side effect of the
  #5 registry fix. A new test (`test_unregistered_model_not_checked`) confirms
  the duplicate came from `resource_registry`'s `Resource` model cascading a
  save and getting logged too; scoping to registered models eliminates it.
- **#4 (bulk operations) — PARTIAL in DAB; service wiring TBD.** The `post_save`
  signal still cannot observe bulk APIs. **`bulk_validation_audit`** provides
  `audit_bulk_model_instances` / `audit_bulk_item_dicts` using the same
  `_protected_models` registry and validators; one unit test asserts log format.
  Closing the epic's sync/import risk requires **downstream PRs** at bulk write
  sites (option 3). No QuerySet monkeypatch; no platform-wide model validator rollout.
- **#5 (no registry) — FIXED, verified.** `CleanTextMixin.__init_subclass__`
  now registers `Meta.model` (plus `name_fields`/`excluded_fields`) into a
  module-level registry, and the signal short-circuits for any unregistered
  model. Three new tests cover registration, no-`Meta.model` safety, and
  `excluded_fields` unioning across multiple serializers for the same model
  (worth noting: `name_fields` is unioned the same way but that isn't called
  out in the doc's caveat — a serializer-specific Tier 1/Tier 2 classification
  difference for the same field name across services would silently resolve
  to whichever configuration was registered, which could misclassify a field
  for one of the services sharing that model).
- **#5a (enforcement-gated logging) — FIXED, verified.** The
  `ENHANCED_INPUT_VALIDATION_ENABLED` early-return has been removed from
  `validation_bypass_logger`. `test_signal_skips_when_validation_disabled` was
  replaced with `test_signal_logs_even_when_enforcement_disabled`, which
  asserts a log entry is produced with enforcement off — matching
  `CleanTextMixin`'s own logging behavior. All 22 tests pass.
- **#6 (platform-wide blast radius) — Partially mitigated; re-assessed after
  the implementing agent proposed the registry as a direct fix for this
  finding.** Three claims were made and are addressed here individually:
  - *"Signal only fires on registered models"* — imprecise. `post_save.connect()`
    still has no `sender` filter, so Django's dispatcher invokes
    `validation_bypass_logger` on every save of every model in every service;
    the registry lookup is an early-return *inside* the handler, not a
    dispatch-level filter. More accurately: the registry makes the *expensive*
    work (stack walk, regex validation) conditional on registration, but a
    small fixed per-save cost (one function call, one dict lookup) is still
    paid platform-wide, unconditionally, for as long as this DAB version is
    deployed.
  - *"No blast radius until they opt in"* — stale. As captured earlier in this
    doc, Service Wiring for Controller/EDA/Hub/Gateway is underway and
    complete for some services already, so registered-model blast radius is
    live now, not a future-only consideration.
  - *"Validation stays default-off"* — enforcement remains gated by
    `ENHANCED_INPUT_VALIDATION_ENABLED` on serializers only; bypass **logging**
    is always on (see #5a). There is no flag to disable the expensive signal
    path for registered ORM bypass saves.

  Net: registry + context-var short-circuit materially reduce cost versus an
  unscoped global validator, but **registered ORM bypass saves** still pay stack
  walk + regex. Load-test registered models under realistic save rates; avoid
  registering hot internal tables unless required.

**Residual risk worth flagging separately:** DRF's `ListSerializer.save()`
(used for `many=True` serializers) calls `child.create()`/`child.update()`
directly rather than `child.save()`, so `CleanTextMixin.save()`'s context-var
wrapping — and therefore the double-logging guard — would not engage for
bulk/list-serializer writes. Not yet confirmed against this codebase's actual
usage of `many=True` with `CleanTextMixin`, but worth a quick check before
calling #1 fully closed.

## Bottom line

DAB side: the signal is **correct and scoped** (#1, #3, #5, #5a), **caller resolution
is implemented** as hybrid allowlist/denylist/fallback (#2), and **bulk audit helpers**
exist (#4) for services to call at sync/import sites. Remaining work is mostly
**downstream**: register caller prefixes per service, wire `audit_bulk_*` at high-risk
bulk paths, load-test registered models (#6), and confirm `many=True` / `ListSerializer`
paths set the serializer context var (#1 residual). Serializer-layer `CleanTextMixin`
with grandfathering remains the enforcement boundary — no model behavior change for this
epic.
