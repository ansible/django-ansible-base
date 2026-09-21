# Review: ORM-Direct Validation Bypass Signal (AAP-86051)

## Summary Status

| Finding | Category | Status |
|---------|----------|--------|
| #1: Double-logging guard | Correctness | ✅ FIXED |
| #2: Caller info | Usability | 🟡 PATCHED (DAB-internal case only) |
| #3: Duplicate log entries | Observability | ✅ FIXED |
| #4: Bulk operations unobservable | Scope | ❓ TBD |
| #5a: Enforcement gating | Consistency | ✅ FIXED |
| #5: No model registry | Scope | ✅ FIXED |
| #6: Platform-wide blast radius | Risk | 🟡 PARTIALLY MITIGATED |

**Net result:** The signal is now trustworthy for its core function (accurate, non-blocking observability on serializer-mediated ORM bypasses). Two correctness issues (#1, #3) and one consistency issue (#5a) are fixed and verified. The registry fix (#5) eliminates false-positive scope problems. Caller attribution (#2) is improved but incomplete; bulk-operation coverage (#4) is deliberately out-of-scope; platform-wide performance (#6) requires load testing before broad deployment.

---

## Open Items & Recommendations

### #2: Caller Info Attribution (Structurally Incomplete)

**Current state:** PATCHED for DAB's own `CommonModel.save()` wrapper; all 22 tests pass. However, when Controller/EDA/Hub/Gateway wire in `CleanTextMixin`, their own base-model `save()` wrappers will have the same "wrong caller" problem — DAB's denylist can't know about them.

**Available approaches:**

1. **Per-service denylist extension:** Each service adds its own internal module prefixes. Pro: local control. Con: maintenance burden spreads, no guarantee of completeness.
2. **Whitelist configuration:** Services explicitly declare `CALLER_INFO_APP_MODULES` so the signal knows their app code. Pro: clear intent. Con: setup burden, requires configuration.
3. **Heuristic: first non-Django frame.** Pro: simple, no config. Con: fragile to library versions, might misidentify.
4. **Heuristic: first frame outside current repo.** Pro: natural boundary. Con: complex to implement, edge cases.

**Recommendation:** Document a pattern (option 1 or 2) for downstream services before they ship their CleanTextMixin wiring, so caller info doesn't regress when they deploy. See [implementation sketches for options 1 & 2](#implementation-sketches-for-options-1--2) in Finding #2 for concrete code examples.

---

### #4: Bulk Operations Coverage (Scope Decision Needed)

**Current state:** TBD. Django doesn't fire signals for `bulk_create()`/`bulk_update()`/`update()`, so this signal structurally can't see them. Yet the ticket's own Goal names sync/import as the "primary motivating risk" — and those use bulk APIs.

**Available approaches:**

1. **Model-level validators** — ❌ Ruled out (requires version updates across all endpoints).
2. **QuerySet method wrapping:** Monkeypatch in DAB. Pro: automatic. Con: **high blast radius**, Django fragility, library interaction risk.
3. **Hook at sync/import site:** Add validation in the services where bulk writes happen (project sync, inventory source updates, collection imports). Pro: **low blast radius**, targeted. Con: coordinated changes across Controller/EDA/Hub/Gateway, doesn't catch other bulk ops.
4. **Ship with documented gap:** Accept that bulk operations aren't observed by this signal. Pro: ships faster, lowest risk. Con: leaves primary risk unobserved.

**Recommendation:** **Option 3 (sync/import hooks)** balances coverage of the actual risk with acceptable scope and blast radius. Requires coordination across services, but that's already happening as they wire in CleanTextMixin.

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

**Optional:** DAB could provide a helper (e.g., `validate_bulk_items(items, model_class)`) to reduce boilerplate across services, but it's not required — services can call the validators directly.

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

## 2. Caller info resolves to Django internals, not the real caller (CONFIRMED — PATCHED for the DAB-internal case, structurally still open; see "Status of fixes" below)

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

Option 2 (whitelist configuration):
```python
# In DAB (ansible_base/lib/utils/validation_signals.py)
from ansible_base.lib.utils.settings import get_setting

def _get_caller_info() -> str:
    try:
        app_modules = get_setting('CALLER_INFO_APP_MODULES', [])
        internal_prefixes = _INTERNAL_CALLER_PREFIXES + app_modules
        
        for frame_info in inspect.stack()[1:]:
            module = inspect.getmodule(frame_info.frame)
            module_name = module.__name__ if module else ''
            if module_name.startswith(tuple(internal_prefixes)):
                continue
            return f"{module_name or 'unknown'}.{frame_info.function}:{frame_info.lineno}"
        return "unknown"
    except Exception:
        return "unknown"

# Then in each service's settings (e.g., AWX settings.py):
CALLER_INFO_APP_MODULES = [
    'awx.main.models',
    'awx.main.tasks',
    'awx.api.views',
]
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

## 4. Bulk operations are silently unobservable (CONFIRMED — coverage is TBD)

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

**Current state:** The latest changes document that bulk operations are not
caught (see `validation_bypass_paths.md`). Whether to expand this story to
close the gap (options 2-3 above) or accept the gap as documented (option 4)
is a scope decision for the team.

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
- **Hot-path performance exposure.** As implemented, the signal runs
  `inspect.stack()` plus regex validation of every text field on *every*
  model save platform-wide once `ENHANCED_INPUT_VALIDATION_ENABLED` is on —
  including high-frequency tables like AWX `JobEvent`/`Host` writes or EDA's
  event tables. Stack introspection in an unfiltered global hook is a known
  way to quietly tax the busiest write paths in every service at once.
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

## Status of fixes (as of latest unstaged changes)

A follow-up round of changes to `ansible_base/lib/serializers/mixins.py`,
`ansible_base/lib/utils/validation_signals.py`, `docs/lib/validation_bypass_paths.md`,
and the test suite addresses most of the above. Verified by re-running the
branch's test suite under `TESTAPP_MODE=sqlite`:

- **#1 (double-logging guard) — FIXED, verified.** The context var is now set
  and reset around `CleanTextMixin.save()` itself (spanning the actual
  `.save()` call and any synchronous `post_save` cascades it triggers), not
  just `validate()`. New regression tests reproduce both scenarios used to
  prove the original bug (a valid serializer create, and a grandfathered-field
  serializer update) and both pass.
- **#2 (caller info) — PATCHED for the DAB-internal case, structurally still open.**
  `_get_caller_info()` walks the stack skipping a denylist of internal module
  prefixes instead of using a fixed frame offset — a better approach in
  principle. A follow-up change added `ansible_base.lib.abstract_models` to
  the denylist (DAB's own `CommonModel`/`CreatableModel` `save()` wrappers,
  which only add bookkeeping like `modified_by` before calling `super().save()`),
  and `test_caller_info_captured` now passes — all 22 tests in the suite pass.
  That said, this closes the one case DAB's own test suite can exercise, not
  the general problem: the denylist only knows about modules living inside
  `ansible_base`. AWX, EDA, Hub, and Gateway each have their own base-model
  `save()` overrides in their own repos (per the primer doc), which this list
  has no way to know about and DAB's tests have no way to catch. The most
  likely outcome is that the first downstream service to wire in `CleanTextMixin`
  reproduces the same "caller resolves to an internal wrapper" symptom for its
  own base model — this needs either a documented pattern for services to
  extend the denylist themselves, or a different detection strategy that
  doesn't rely on an enumerated list of "known internal" modules.
- **#3 (duplicate log entries) — FIXED, verified**, as a side effect of the
  #5 registry fix. A new test (`test_unregistered_model_not_checked`) confirms
  the duplicate came from `resource_registry`'s `Resource` model cascading a
  save and getting logged too; scoping to registered models eliminates it.
- **#4 (bulk operations) — COVERAGE IS TBD.** Django structurally doesn't fire
  signals for `bulk_create()`/`bulk_update()`/`update()`, so this signal
  cannot observe them. See finding #4 above for four concrete approaches to
  close the gap (model validators, QuerySet wrapping, site-specific hooks, or
  accepting the gap as documented). Whether to expand this story's scope to
  implement one of those, or ship with the documented limitation, is a scope
  decision for the team.
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
  - *"Validation stays default-off"* — this leaned on the
    `ENHANCED_INPUT_VALIDATION_ENABLED` gate as a safety net, but that gate
    was just removed (see #5a) for good reason (it made the signal
    inconsistent with `CleanTextMixin`'s own always-log behavior). With it
    gone, there is no remaining environment-level throttle on the expensive
    path — once a model is registered, every save of it pays full validation
    cost unconditionally. Fixing #5a correctly *removes* the safety net #6's
    original mitigation claim depended on.

  Net: the registry fix is a real, correctly-targeted improvement — it
  eliminates wasted work on irrelevant models and was the right call — but it
  mitigates the *false-positive/scope* dimension of the risk (closer to
  finding #5) more than the *platform-wide performance/incident-blast-radius*
  dimension #6 was actually about. For whichever models get registered first
  (increasingly the common, busy resources as Service Wiring completes), the
  original hot-path concern — full stack-walk-plus-regex-validation cost on
  every save, now with no enforcement-flag throttle — stands unchanged. This
  argues for load-testing the registered path specifically, not for treating
  #6 as closed.

**Residual risk worth flagging separately:** DRF's `ListSerializer.save()`
(used for `many=True` serializers) calls `child.create()`/`child.update()`
directly rather than `child.save()`, so `CleanTextMixin.save()`'s context-var
wrapping — and therefore the double-logging guard — would not engage for
bulk/list-serializer writes. Not yet confirmed against this codebase's actual
usage of `many=True` with `CleanTextMixin`, but worth a quick check before
calling #1 fully closed.

## Bottom line

The correctness issues that made the signal untrustworthy at first pass — the
broken double-logging guard (#1) and the false-positive noise from having no
model registry (#5, and its knock-on duplicate-entry effect, #3) — are now
fixed and verified by regression tests. What remains open is narrower but
still real: caller info (#2) still misattributes to internal `save()`
wrappers rather than the actual bypass site, which limits the audit log's
usefulness for its stated purpose even though the log itself is now accurate
about *whether* a bypass happened. #4 (bulk sync/import operations) remains
fully unobservable by design — correctly documented now rather than silently
implied as covered — and would need a different mechanism entirely if this
story's scope is expanded to close it. And because DAB sits at the base of
every component (#6), any further expansion — especially one that touches
`bulk_create`/`update()` via monkeypatching — needs to be evaluated for
platform-wide blast radius, not just correctness within this repo.
