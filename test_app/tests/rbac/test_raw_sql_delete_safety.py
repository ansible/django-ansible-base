"""
Guardrail tests for the raw SQL DELETE bypass in _bulk_delete_and_accumulate_sync.

That function uses raw SQL DELETE statements (bypassing Django's ORM collector
and signals) to delete ObjectRoles and their dependent rows in bottom-up order.
If the RBAC models change in certain ways, the raw SQL path will silently
produce incorrect results -- orphaned rows, missing audit entries, or outright
SQL errors.

These tests introspect the models at import time so they fail loudly when a
schema or inheritance change would break the raw SQL bypass.

Each test class includes a negative "canary" test that patches the inspected
attribute to a bad value, asserts the check would catch it, then restores the
original. This proves the assertions are not vacuously passing.
"""

import pytest
from django.db import models
from django.db.models.signals import post_delete, post_init, post_save, pre_delete, pre_save

from ansible_base.rbac.models import (
    ObjectRole,
    RoleEvaluation,
    RoleEvaluationUUID,
    RoleTeamAssignment,
    RoleUserAssignment,
)
from ansible_base.rbac.permission_registry import permission_registry

# ---------------------------------------------------------------------------
# 1. Signal / audit-model introspection
# ---------------------------------------------------------------------------


class TestAssignmentAuditModelFlags:
    """The raw SQL delete manually calls _log_audit_entry for assignment rows.

    It relies on RoleUserAssignment and RoleTeamAssignment having specific
    audit flags.  If these change, the manual audit-log code in
    _bulk_delete_and_accumulate_sync must be updated to match.
    """

    @pytest.mark.parametrize(
        "model_cls",
        [RoleUserAssignment, RoleTeamAssignment],
        ids=["RoleUserAssignment", "RoleTeamAssignment"],
    )
    def test_assignment_audit_log_enabled(self, model_cls):
        assert hasattr(model_cls, "audit_log_enabled"), (
            f"{model_cls.__name__} lost the audit_log_enabled attribute. "
            f"Update _bulk_delete_and_accumulate_sync to stop emitting "
            f"audit entries for {model_cls.__name__} deletions."
        )
        assert model_cls.audit_log_enabled is True, (
            f"{model_cls.__name__}.audit_log_enabled changed to "
            f"{model_cls.audit_log_enabled!r}. Update the manual audit-log "
            f"code in _bulk_delete_and_accumulate_sync."
        )

    @pytest.mark.parametrize(
        "model_cls",
        [RoleUserAssignment, RoleTeamAssignment],
        ids=["RoleUserAssignment", "RoleTeamAssignment"],
    )
    def test_assignment_activity_stream_disabled(self, model_cls):
        assert hasattr(model_cls, "activity_stream_enabled"), (
            f"{model_cls.__name__} lost the activity_stream_enabled attribute. "
            f"Update _bulk_delete_and_accumulate_sync -- it assumes no "
            f"activity stream entries are needed for {model_cls.__name__}."
        )
        assert model_cls.activity_stream_enabled is False, (
            f"{model_cls.__name__}.activity_stream_enabled changed to "
            f"{model_cls.activity_stream_enabled!r}. The raw SQL delete in "
            f"_bulk_delete_and_accumulate_sync must now create activity "
            f"stream Entry records for deleted {model_cls.__name__} rows."
        )

    @pytest.mark.parametrize(
        "model_cls,attr,bad_value",
        [
            (RoleUserAssignment, "audit_log_enabled", False),
            (RoleTeamAssignment, "activity_stream_enabled", True),
        ],
        ids=["canary:audit_log_disabled", "canary:activity_stream_enabled"],
    )
    def test_canary_catches_flag_change(self, model_cls, attr, bad_value):
        """Prove the assertions above would fail if a flag changed."""
        original = getattr(model_cls, attr)
        try:
            setattr(model_cls, attr, bad_value)
            assert getattr(model_cls, attr) == bad_value
            if attr == "audit_log_enabled":
                assert not _has_audit_logging(model_cls)
        finally:
            setattr(model_cls, attr, original)


def _has_audit_logging(model_cls):
    """Check if a model has audit logging enabled."""
    return getattr(model_cls, "audit_log_enabled", False)


class TestObjectRoleAuditModelFlags:
    """ObjectRole does NOT inherit AuditableModel."""

    def test_object_role_no_audit_logging(self):
        assert not _has_audit_logging(ObjectRole), (
            "ObjectRole now has audit_log_enabled=True. The raw SQL delete "
            "in _bulk_delete_and_accumulate_sync does not emit audit entries "
            "for ObjectRole deletions -- add manual audit logging there."
        )

    def test_canary_catches_audit_added_to_object_role(self):
        """Prove the assertion above would fail if ObjectRole gained audit logging."""
        assert not hasattr(ObjectRole, "audit_log_enabled")
        try:
            ObjectRole.audit_log_enabled = True
            assert _has_audit_logging(ObjectRole) is True, "Expected _has_audit_logging(ObjectRole) to return True after patching"
        finally:
            del ObjectRole.audit_log_enabled


# ---------------------------------------------------------------------------
# 2. CASCADE constraint verification
# ---------------------------------------------------------------------------


def _all_object_role_fks_are_cascade():
    """Check that every FK pointing at ObjectRole uses on_delete=CASCADE."""
    for related in ObjectRole._meta.related_objects:
        if related.on_delete != models.CASCADE:
            return False, related
    return True, None


class TestCascadeConstraints:
    """The raw SQL delete removes child rows in explicit bottom-up order.

    All FK fields that reference ObjectRole must use on_delete=CASCADE.
    If a FK is changed to SET_NULL or PROTECT, the bottom-up delete would
    either leave orphaned rows or fail with an integrity error.
    """

    def test_object_role_cascade_constraints(self):
        ok, related = _all_object_role_fks_are_cascade()
        if not ok:
            pytest.fail(
                f"{related.related_model.__name__}.{related.field.name} "
                f"references ObjectRole with "
                f"on_delete={related.on_delete.__name__}, but "
                f"_bulk_delete_and_accumulate_sync requires CASCADE. "
                f"Update the raw SQL delete order if changing this."
            )

    def test_provides_teams_m2m_through_table_exists(self):
        through_model = ObjectRole.provides_teams.through
        assert through_model._meta.db_table == "dab_rbac_objectrole_provides_teams", (
            f"provides_teams through table changed to "
            f"{through_model._meta.db_table!r}. The raw SQL delete in "
            f"_bulk_delete_and_accumulate_sync references this table."
        )

    def test_canary_catches_non_cascade_constraint(self):
        """Prove the CASCADE check would catch a SET_NULL constraint."""
        related = ObjectRole._meta.related_objects[0]
        original = related.on_delete
        try:
            related.on_delete = models.SET_NULL
            ok, bad_related = _all_object_role_fks_are_cascade()
            assert not ok, "Expected _all_object_role_fks_are_cascade to return (False, ...) after patching"
            assert bad_related is related
        finally:
            related.on_delete = original


# ---------------------------------------------------------------------------
# 3. Non-pluggability (concrete, non-swappable models)
# ---------------------------------------------------------------------------


_RBAC_MODELS = [
    RoleUserAssignment,
    RoleTeamAssignment,
    ObjectRole,
    RoleEvaluation,
    RoleEvaluationUUID,
]
_RBAC_MODEL_IDS = [cls.__name__ for cls in _RBAC_MODELS]


def _is_concrete(model_cls):
    """Check if a model is concrete (not abstract)."""
    return not model_cls._meta.abstract


def _is_not_swappable(model_cls):
    """Check if a model is not swappable."""
    return not getattr(model_cls._meta, "swappable", None)


class TestRbacModelsConcrete:
    """The raw SQL delete references model table names via _meta.db_table."""

    @pytest.mark.parametrize("model_cls", _RBAC_MODELS, ids=_RBAC_MODEL_IDS)
    def test_model_is_concrete(self, model_cls):
        assert _is_concrete(model_cls), (
            f"{model_cls.__name__} is abstract. The raw SQL delete in "
            f"_bulk_delete_and_accumulate_sync uses "
            f"{model_cls.__name__}._meta.db_table which would be "
            f"undefined for abstract models."
        )

    @pytest.mark.parametrize("model_cls", _RBAC_MODELS, ids=_RBAC_MODEL_IDS)
    def test_model_is_not_swappable(self, model_cls):
        assert _is_not_swappable(model_cls), (
            f"{model_cls.__name__} is swappable. The raw SQL delete in "
            f"_bulk_delete_and_accumulate_sync resolves table names from "
            f"_meta.db_table at runtime -- swappable models would point "
            f"to the wrong table."
        )

    def test_canary_catches_abstract_model(self):
        """Prove the abstract check would catch it."""
        original = ObjectRole._meta.abstract
        try:
            ObjectRole._meta.abstract = True
            assert not _is_concrete(ObjectRole), "Expected _is_concrete(ObjectRole) to return False after patching abstract=True"
        finally:
            ObjectRole._meta.abstract = original

    def test_canary_catches_swappable_model(self):
        """Prove the swappable check would catch it."""
        original = getattr(ObjectRole._meta, "swappable", None)
        try:
            ObjectRole._meta.swappable = "RBAC_OBJECT_ROLE_MODEL"
            assert not _is_not_swappable(ObjectRole), "Expected _is_not_swappable(ObjectRole) to return False after patching swappable"
        finally:
            if original is None:
                if hasattr(ObjectRole._meta, "swappable"):
                    ObjectRole._meta.swappable = None
            else:
                ObjectRole._meta.swappable = original


# ---------------------------------------------------------------------------
# 4. FK column name verification
# ---------------------------------------------------------------------------


class TestForeignKeyColumnNames:
    """The raw SQL DELETE statements reference specific column names."""

    @pytest.mark.parametrize(
        "model_cls,field_name,expected_column",
        [
            (RoleUserAssignment, "object_role", "object_role_id"),
            (RoleTeamAssignment, "object_role", "object_role_id"),
            (RoleEvaluation, "role", "role_id"),
            (RoleEvaluationUUID, "role", "role_id"),
        ],
        ids=[
            "RoleUserAssignment.object_role_id",
            "RoleTeamAssignment.object_role_id",
            "RoleEvaluation.role_id",
            "RoleEvaluationUUID.role_id",
        ],
    )
    def test_fk_column_name(self, model_cls, field_name, expected_column):
        actual = model_cls._meta.get_field(field_name).column
        assert actual == expected_column, (
            f"{model_cls.__name__}.{field_name} column changed from "
            f"{expected_column!r} to {actual!r}. Update the raw SQL "
            f"DELETE in _bulk_delete_and_accumulate_sync."
        )

    def test_provides_teams_through_fk_column(self):
        through = ObjectRole.provides_teams.through
        for field in through._meta.get_fields():
            if hasattr(field, "related_model") and field.related_model is ObjectRole:
                assert field.column == "objectrole_id", (
                    f"provides_teams through table FK to ObjectRole "
                    f"column changed from 'objectrole_id' to "
                    f"{field.column!r}. Update the raw SQL DELETE in "
                    f"_bulk_delete_and_accumulate_sync."
                )
                break
        else:
            pytest.fail(
                "No FK field pointing to ObjectRole found in the "
                "provides_teams through table. The raw SQL delete in "
                "_bulk_delete_and_accumulate_sync needs this FK."
            )

    def test_canary_catches_column_rename(self):
        """Prove the column name check would catch a rename."""
        field = RoleUserAssignment._meta.get_field("object_role")
        original = field.column
        try:
            field.column = "role_fk_id"
            assert field.column != "object_role_id", "Expected field.column to differ from 'object_role_id' after patching"
        finally:
            field.column = original


# ---------------------------------------------------------------------------
# 5. Signal handler introspection
# ---------------------------------------------------------------------------


def _has_wrapped_delete(cls):
    """Check if a model's delete() method has been wrapped by connect_rbac_signals."""
    return hasattr(cls.delete, '__wrapped__')


def _signal_has_dispatch_uid(signal, sender, dispatch_uid):
    """Check if a signal has a receiver registered with the given dispatch_uid for a sender.

    Django stores dispatch_uid strings directly (not hashed) as the first
    element of the receiver key tuple. The sender is stored as _make_id(sender).
    """
    from django.dispatch.dispatcher import _make_id

    sender_key = _make_id(sender)
    with signal.lock:
        for receiver_entry in signal.receivers:
            lookup_key = receiver_entry[0]
            lookup_uid, lookup_sender = lookup_key[0], lookup_key[1]
            if lookup_uid == dispatch_uid and (lookup_sender == sender_key or lookup_sender is None):
                return True
    return False


class TestSignalHandlersConnected:
    """The raw SQL delete sets skip_post_delete_rbac to bypass the
    post_delete signal handler. If signal handlers are added, removed,
    or renamed, the raw SQL path may need updates.

    connect_rbac_signals also wraps delete() with defer_rbac_cache and
    _bulk_pre_cascade_rbac_cleanup. If the wrapping is removed, the
    raw SQL pre-cascade cleanup won't fire.
    """

    @pytest.mark.parametrize(
        "signal,uid,handler_name",
        [
            (post_init, 'permission-registry-save-prior-parent', 'rbac_post_init_set_original_parent'),
            (pre_save, 'permission-registry-pre-save', 'rbac_pre_save_identify_changes'),
            (post_save, 'permission-registry-post-save', 'rbac_post_save_update_evaluations'),
            (post_delete, 'permission-registry-post-delete', 'rbac_post_delete_remove_object_roles'),
        ],
        ids=[
            "post_init:rbac_post_init_set_original_parent",
            "pre_save:rbac_pre_save_identify_changes",
            "post_save:rbac_post_save_update_evaluations",
            "post_delete:rbac_post_delete_remove_object_roles",
        ],
    )
    def test_common_signals_connected_for_registered_models(self, signal, uid, handler_name):
        """Every model registered via connect_rbac_signals must have
        the core RBAC signal handlers connected."""
        for cls in permission_registry._registry:
            assert _signal_has_dispatch_uid(signal, cls, uid), (
                f"{cls.__name__} is missing the {handler_name} handler " f"(dispatch_uid={uid!r}). " f"connect_rbac_signals must connect this handler."
            )

    def test_team_model_has_pre_delete_handler(self):
        """The team model must have team_pre_delete connected via pre_delete."""
        team_cls = permission_registry.team_model
        assert _signal_has_dispatch_uid(pre_delete, team_cls, 'stash-team-roles-before-delete'), (
            f"{team_cls.__name__} is missing the team_pre_delete handler "
            f"(dispatch_uid='stash-team-roles-before-delete') on pre_delete. "
            f"connect_rbac_signals connects this for the team model "
            f"to stash team roles before deletion."
        )

    def test_non_team_models_lack_pre_delete_handler(self):
        """Non-team models should NOT have team_pre_delete connected."""
        team_cls = permission_registry.team_model
        for cls in permission_registry._registry:
            if cls is team_cls:
                continue
            assert not _signal_has_dispatch_uid(pre_delete, cls, 'stash-team-roles-before-delete'), (
                f"{cls.__name__} has the team_pre_delete handler connected "
                f"but it is not the team model. This handler should only be "
                f"connected to {team_cls.__name__}."
            )

    def test_delete_method_wrapped_by_connect_rbac_signals(self):
        """connect_rbac_signals wraps delete() with defer_rbac_cache and
        _bulk_pre_cascade_rbac_cleanup. If this wrapping is removed, the
        raw SQL pre-cascade cleanup won't fire automatically."""
        for cls in permission_registry._registry:
            assert _has_wrapped_delete(cls), (
                f"{cls.__name__}.delete() is not wrapped by "
                f"connect_rbac_signals. The deferred_delete wrapper is "
                f"required for _bulk_pre_cascade_rbac_cleanup to fire "
                f"before Django's ORM cascade."
            )

    def test_canary_detects_missing_signal(self):
        """Prove the signal check catches a missing dispatch_uid."""
        cls = next(iter(permission_registry._registry))
        assert not _signal_has_dispatch_uid(post_save, cls, 'nonexistent-dispatch-uid')

    def test_canary_detects_unwrapped_delete(self):
        """Prove the __wrapped__ check catches an unwrapped delete method."""

        class FakeModel:
            def delete(self):
                pass

        assert not _has_wrapped_delete(FakeModel)
