# Review: ORM-Direct Validation Bypass Signal (AAP-86051)

Findings from reviewing the staged changes implementing the `post_save`-based
validation bypass logger (`ansible_base/lib/utils/validation_signals.py`,
`ansible_base/lib/serializers/mixins.py`, `ansible_base/observability/apps.py`,
`docs/lib/validation_bypass_paths.md`, `test_app/tests/lib/utils/test_validation_signals.py`).

All findings below except the last were empirically reproduced by running the
branch's own test suite under `TESTAPP_MODE=sqlite` (no Postgres available in
this environment) and by scripting two additional scenarios the existing tests
don't cover: a fully valid serializer-mediated save, and a grandfathered-field
serializer update.

## 1. Double-logging guard does not work for real writes (CONFIRMED)

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

## 2. Caller info resolves to Django internals, not the real caller (CONFIRMED)

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

## 3. Duplicate log entries for a single save (CONFIRMED)

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

## 4. Bulk operations are silently unobservable despite being documented as covered (CONFIRMED)

**File:** `docs/lib/validation_bypass_paths.md:341`

The doc lists `bulk_create()` / `bulk_update()` / `QuerySet.update()` as
bypass paths, but `post_save` (the only hook implemented) is never fired by
those APIs, so the signal cannot detect them at all.

Project sync / inventory source update / collection import — the exact
examples given under "Bulk Operations" and cited in the Jira ticket's Goal as
the primary motivating risk — use `bulk_create`/`queryset.update` in
practice, and none of those writes will ever reach `validation_bypass_logger`.
This silently leaves the highest-risk category (rated "Medium to High" in
this same doc) with zero observability, despite the doc implying the signal
covers it.

## 5. No registry of protected models — likely false-positive noise once services start wiring in CleanTextMixin (PLAUSIBLE)

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

## 6. Platform-wide blast radius from unscoped registration in a shared library (RISK)

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
- **#2 (caller info) — IMPROVED, still fails.** `_get_caller_info()` now walks
  the stack skipping a denylist of internal module prefixes instead of using a
  fixed frame offset — a better approach in principle. But `test_caller_info_captured`
  still fails: it resolves to `ansible_base.lib.abstract_models.common.save:141`
  (DAB's own `CommonModel.save()` wrapper) instead of the real caller. The
  denylist only knows about `django.db.models`, `django.dispatch`, and its own
  module — not DAB's or any downstream service's base-model `save()` overrides
  (AWX, EDA, Hub, and Gateway each have their own, per the primer doc). This is
  a structural limitation of the denylist approach, not a one-line miss: it
  would need indefinite maintenance to stay accurate platform-wide.
- **#3 (duplicate log entries) — FIXED, verified**, as a side effect of the
  #5 registry fix. A new test (`test_unregistered_model_not_checked`) confirms
  the duplicate came from `resource_registry`'s `Resource` model cascading a
  save and getting logged too; scoping to registered models eliminates it.
- **#4 (bulk operations) — Correctly left unfixed, now explicitly documented**
  as a structural limitation (Django fires no signal for `bulk_create`/
  `bulk_update`/`update()`) rather than silently implied as covered. This
  matches the earlier recommendation to descope rather than force a fix into
  this story.
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
- **#6 (platform-wide blast radius) — Partially mitigated.** The registry
  short-circuit shrinks the hot-path cost for unregistered models to a single
  dict lookup, which helps. But `post_save.connect()` is still global/unscoped,
  and for models that *are* registered, full field validation (including
  `inspect.stack()` walking) still runs on every save — so the performance
  question for busy, already-wired models (increasingly relevant now that
  Service Wiring is underway/complete for some services, per the update to
  finding #5) is not resolved by this fix.

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
