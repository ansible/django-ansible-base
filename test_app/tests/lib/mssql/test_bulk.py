"""Tests for ansible_base.lib.mssql.bulk — transparent MS SQL Server bulk writes."""

from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, call

import pytest
from django.db import IntegrityError, connection
from django.db.models import QuerySet
from django.db.models.signals import post_save, pre_save

from ansible_base.lib.mssql import bulk as bulk_module
from ansible_base.lib.mssql.bulk import MSSQLSafeQuerySet
from ansible_base.lib.mssql.bulk import bulk_create as bulk_create_function
from test_app.models import ExampleEvent


def make_connection(*, vendor="microsoft", can_return_rows=True, supports_ignore_conflicts=False):
    return SimpleNamespace(
        vendor=vendor,
        features=SimpleNamespace(
            can_return_rows_from_bulk_insert=can_return_rows,
            supports_ignore_conflicts=supports_ignore_conflicts,
        ),
        needs_rollback=False,
    )


def make_queryset(monkeypatch, *, using="default", **connection_kwargs):
    fake = make_connection(**connection_kwargs)
    monkeypatch.setattr(bulk_module, "connections", {"default": fake, "replica": fake})
    queryset = MSSQLSafeQuerySet(model=ExampleEvent, using=using)
    queryset._prepare_for_bulk_create = Mock()
    return queryset, fake


def patch_savepoints(monkeypatch, savepoint_ids):
    savepoint = Mock(side_effect=savepoint_ids)
    commit = Mock()
    rollback = Mock()
    monkeypatch.setattr(bulk_module.transaction, "savepoint", savepoint)
    monkeypatch.setattr(bulk_module.transaction, "savepoint_commit", commit)
    monkeypatch.setattr(bulk_module.transaction, "savepoint_rollback", rollback)
    return savepoint, commit, rollback


def patch_super_bulk_create(monkeypatch, **kwargs):
    """Patch QuerySet.bulk_create (what MSSQLSafeQuerySet.bulk_create delegates to)."""
    spy = Mock(**kwargs)
    monkeypatch.setattr(QuerySet, "bulk_create", spy)
    return spy


def make_event(name="evt", pk=None):
    return ExampleEvent(id=pk, name=name)


def test_bulk_create_delegates_to_super_on_postgres(monkeypatch):
    queryset, _ = make_queryset(monkeypatch, vendor="postgresql", supports_ignore_conflicts=True)
    spy = patch_super_bulk_create(monkeypatch, return_value=[])
    objs = [make_event("a")]

    queryset.bulk_create(objs, batch_size=7, ignore_conflicts=True)

    spy.assert_called_once_with(objs, batch_size=7, ignore_conflicts=True)


def test_bulk_create_delegates_to_super_when_ignore_conflicts_supported(monkeypatch):
    "mssql-django turns ignore_conflicts support on in a future version: no interception."
    queryset, _ = make_queryset(monkeypatch, supports_ignore_conflicts=True)
    spy = patch_super_bulk_create(monkeypatch, return_value=[])
    objs = [make_event("a")]

    queryset.bulk_create(objs, ignore_conflicts=True)

    spy.assert_called_once_with(objs, batch_size=None, ignore_conflicts=True)


def test_bulk_create_microsoft_without_ignore_conflicts_uses_super(monkeypatch):
    "With return_rows_bulk_insert on (PR 2 default) the plain path needs no help."
    queryset, _ = make_queryset(monkeypatch, can_return_rows=True)
    spy = patch_super_bulk_create(monkeypatch, return_value=[])
    objs = [make_event("a")]

    queryset.bulk_create(objs, ignore_conflicts=False)

    spy.assert_called_once_with(objs, batch_size=None, ignore_conflicts=False)


def test_bulk_create_update_conflicts_not_special_cased(monkeypatch):
    "update_conflicts is unsupported on mssql-django; Django's own NotSupportedError must surface."
    queryset, _ = make_queryset(monkeypatch, supports_ignore_conflicts=False)
    spy = patch_super_bulk_create(monkeypatch, side_effect=NotImplementedError("django decides"))
    objs = [make_event("a")]

    with pytest.raises(NotImplementedError):
        queryset.bulk_create(objs, update_conflicts=True, unique_fields=["name"], update_fields=["name"])

    spy.assert_called_once()


def test_bulk_create_ignoring_conflicts_retries_per_row_after_batch_failure(monkeypatch):
    queryset, fake = make_queryset(monkeypatch, can_return_rows=True, supports_ignore_conflicts=False)
    savepoint, commit, rollback = patch_savepoints(monkeypatch, ("batch", "row-dup", "row-ok"))
    spy = patch_super_bulk_create(monkeypatch, side_effect=IntegrityError("batch conflicted"))
    duplicate = make_event("dup")
    fresh = make_event("fresh")
    queryset._insert = Mock(side_effect=[IntegrityError("duplicate"), [(88,)]])

    result = queryset.bulk_create([duplicate, fresh], ignore_conflicts=True)

    spy.assert_called_once_with([duplicate, fresh], batch_size=None, ignore_conflicts=False)
    assert result == [fresh]
    assert fresh.id == 88
    assert savepoint.call_count == 3
    rollback.assert_has_calls([call("batch", using="default"), call("row-dup", using="default")])
    commit.assert_called_once_with("row-ok", using="default")
    assert fake.needs_rollback is False


def test_bulk_create_ignoring_conflicts_sets_state_and_pk(monkeypatch):
    "Per-row retry results carry a populated PK and a settled _state, like plain bulk_create."
    queryset, _ = make_queryset(monkeypatch, can_return_rows=True, supports_ignore_conflicts=False)
    patch_savepoints(monkeypatch, ("batch", "row"))
    patch_super_bulk_create(monkeypatch, side_effect=IntegrityError("batch conflicted"))
    obj = make_event("fresh")
    queryset._insert = Mock(return_value=[(88,)])

    result = queryset.bulk_create([obj], ignore_conflicts=True)

    assert result == [obj]
    assert obj.id == 88
    assert obj._state.db == "default"
    assert obj._state.adding is False


def test_bulk_create_per_row_skips_unset_autofield(monkeypatch):
    "Unset AutoField PKs are left to the database, exactly like Django's own bulk paths."
    queryset, _ = make_queryset(monkeypatch, can_return_rows=True, supports_ignore_conflicts=False)
    patch_savepoints(monkeypatch, ("batch", "row", "batch-2", "row-2"))
    patch_super_bulk_create(monkeypatch, side_effect=IntegrityError("batch conflicted"))
    obj = make_event("fresh")
    queryset._insert = Mock(return_value=[(88,)])

    queryset.bulk_create([obj], ignore_conflicts=True)

    inserted_fields = queryset._insert.call_args.args[1]
    assert inserted_fields == [ExampleEvent._meta.get_field("name")]

    # with the PK set it is included
    obj_with_pk = make_event("named", pk=42)
    queryset._insert.reset_mock()
    queryset.bulk_create([obj_with_pk], ignore_conflicts=True)
    inserted_fields = queryset._insert.call_args.args[1]
    assert ExampleEvent._meta.get_field("id") in inserted_fields


def test_ignore_conflicts_without_row_return_skips_batch_attempt(monkeypatch):
    "When the backend cannot return rows from a batch, go straight to per-row inserts (old return_ids=True path)."
    queryset, _ = make_queryset(monkeypatch, can_return_rows=False, supports_ignore_conflicts=False)
    savepoint, commit, rollback = patch_savepoints(monkeypatch, ("row",))
    spy = patch_super_bulk_create(monkeypatch)
    obj = make_event("fresh")
    queryset._insert = Mock(return_value=[(88,)])

    result = queryset.bulk_create([obj], ignore_conflicts=True)

    spy.assert_not_called()
    assert result == [obj] and obj.id == 88
    savepoint.assert_called_once_with(using="default")
    commit.assert_called_once_with("row", using="default")
    rollback.assert_not_called()


def test_bulk_create_falls_back_to_savepoints_when_rows_not_returnable(monkeypatch):
    "User opted out of return_rows_bulk_insert: batches of 50, one row per _insert."
    queryset, _ = make_queryset(monkeypatch, can_return_rows=False)
    savepoint, commit, rollback = patch_savepoints(monkeypatch, ("batch-1", "batch-2"))
    spy = patch_super_bulk_create(monkeypatch)
    pre_save_receivers = pre_save.receivers
    post_save_receivers = post_save.receivers
    objs = [make_event(f"evt-{i}") for i in range(51)]
    next_id = iter(range(1, 52))
    queryset._insert = Mock(side_effect=lambda *args, **kwargs: [(next(next_id),)])

    result = queryset.bulk_create(objs, ignore_conflicts=False)

    spy.assert_not_called()
    assert result == objs
    assert queryset._insert.call_count == 51
    assert savepoint.call_count == 2
    assert commit.call_count == 2
    rollback.assert_not_called()
    assert [obj.id for obj in objs] == list(range(1, 52))
    assert all(obj._state.db == "default" and obj._state.adding is False for obj in objs)
    # per-row _insert fires no signals
    assert pre_save.receivers == pre_save_receivers
    assert post_save.receivers == post_save_receivers


def test_bulk_create_savepoint_fallback_rolls_back_failed_batch(monkeypatch):
    queryset, _ = make_queryset(monkeypatch, can_return_rows=False)
    _, commit, rollback = patch_savepoints(monkeypatch, ("batch-1",))
    obj = make_event("fresh")
    obj.save = Mock(side_effect=RuntimeError("save must not be called"))
    queryset._insert = Mock(side_effect=RuntimeError("insert failed"))

    with pytest.raises(RuntimeError, match="insert failed"):
        queryset.bulk_create([obj], ignore_conflicts=False)

    obj.save.assert_not_called()
    commit.assert_not_called()
    rollback.assert_called_once_with("batch-1", using="default")


def test_bulk_update_delegates_to_super_on_postgres(monkeypatch):
    queryset, _ = make_queryset(monkeypatch, vendor="postgresql")
    spy = Mock(return_value=2)
    monkeypatch.setattr(QuerySet, "bulk_update", spy)
    objs = [make_event("a", pk=1)]

    queryset.bulk_update(objs, ["name"], batch_size=10)

    spy.assert_called_once_with(objs, ["name"], batch_size=10)


def test_bulk_update_clamps_explicit_batch_size_on_microsoft(monkeypatch):
    "mssql-django clamps batch_size=None itself (bulk_batch_size); explicit sizes are our job."
    queryset, _ = make_queryset(monkeypatch)
    spy = Mock(return_value=0)
    monkeypatch.setattr(QuerySet, "bulk_update", spy)
    objs = [make_event("a", pk=1)]

    # 3 fields x N rows CASE-WHEN parameters: (2100 - 100) // 3 = 666
    queryset.bulk_update(objs, ["f1", "f2", "f3"], batch_size=800)
    spy.assert_called_with(objs, ["f1", "f2", "f3"], batch_size=666)

    # a smaller explicit batch is never grown
    queryset.bulk_update(objs, ["f1", "f2", "f3"], batch_size=10)
    spy.assert_called_with(objs, ["f1", "f2", "f3"], batch_size=10)

    # batch_size=None goes through untouched: mssql-django's bulk_batch_size applies
    queryset.bulk_update(objs, ["name"], batch_size=None)
    spy.assert_called_with(objs, ["name"], batch_size=None)


def test_function_form_delegates_through_queryset(monkeypatch):
    fake = make_connection(vendor="postgresql", supports_ignore_conflicts=True)
    monkeypatch.setattr(bulk_module, "connections", {"default": fake, "replica": fake})
    spy = patch_super_bulk_create(monkeypatch, return_value=[])
    objs = [make_event("a")]

    bulk_create_function(ExampleEvent, objs, ignore_conflicts=True, using="replica")

    spy.assert_called_once_with(objs, batch_size=None, ignore_conflicts=True)


def test_function_form_resolves_write_router_alias(monkeypatch):
    fake = make_connection(vendor="postgresql", supports_ignore_conflicts=True)
    monkeypatch.setattr(bulk_module, "connections", {"default": fake, "replica": fake})
    seen = {}

    def fake_super_bulk_create(self, objs, **kwargs):
        seen["db"] = self.db
        return []

    monkeypatch.setattr(QuerySet, "bulk_create", fake_super_bulk_create)
    monkeypatch.setattr(bulk_module, "router", SimpleNamespace(db_for_write=Mock(return_value="replica")))

    bulk_create_function(ExampleEvent, [make_event("a")], ignore_conflicts=True)

    assert seen["db"] == "replica"


@pytest.mark.django_db
class TestBulkCreateLive:
    @skipUnless(connection.vendor == "microsoft", "MS SQL Server only: postgres has native ignore_conflicts")
    def test_bulk_create_ignore_conflicts_live(self):
        from test_app.models import ExampleEvent as Event

        Event.objects.create(name="taken")
        fresh = Event(name="fresh-1")
        duplicate = Event(name="taken")

        result = MSSQLSafeQuerySet(model=Event).bulk_create([duplicate, fresh], ignore_conflicts=True)

        assert result == [fresh]
        assert fresh.pk is not None
        assert Event.objects.filter(name__in=["taken", "fresh-1"]).count() == 2

    def test_bulk_create_returns_pks_live(self):
        from test_app.models import ExampleEvent as Event

        objs = [Event(name=f"pk-probe-{i}") for i in range(3)]

        result = MSSQLSafeQuerySet(model=Event).bulk_create(objs)

        assert len(result) == 3
        assert all(obj.pk is not None and obj._state.adding is False for obj in result)


class TestManagerAttachment:
    "Task 2: the shared bases hand every model a bulk-safe default manager."

    SAFE_MANAGER_MODELS = [
        ("dab_activitystream", "Entry"),
        ("dab_authentication", "Authenticator"),
        ("dab_authentication", "AuthenticatorMap"),
        ("dab_feature_flags", "AAPFlag"),
        ("dab_oauth2_provider", "OAuth2AccessToken"),
        ("dab_oauth2_provider", "OAuth2Application"),
        ("dab_oauth2_provider", "OAuth2IDToken"),
        ("dab_oauth2_provider", "OAuth2RefreshToken"),
        ("dab_rbac", "ObjectRole"),
        ("dab_rbac", "RoleEvaluation"),
        ("dab_rbac", "RoleEvaluationUUID"),
        ("dab_rbac", "RoleUserAssignment"),
        ("dab_rbac", "RoleTeamAssignment"),
        ("dab_rbac", "DABPermission"),
        ("dab_rbac", "DABContentType"),
        ("dab_rbac", "RoleDefinition"),
        ("dab_resource_registry", "Resource"),
    ]

    @pytest.mark.parametrize("app_label,model_name", SAFE_MANAGER_MODELS)
    def test_models_dispatch_bulk_writes_through_mssql_safe_queryset(self, app_label, model_name):
        from django.apps import apps

        model = apps.get_model(app_label, model_name)
        assert model.objects.get_queryset().__class__ is MSSQLSafeQuerySet, f"{app_label}.{model_name}"

    def test_abstract_dab_user_manager_unchanged(self):
        "Users are never bulk-written with ignore_conflicts; UserManager stays."
        from django.contrib.auth import get_user_model

        assert get_user_model().objects.get_queryset().__class__ is not MSSQLSafeQuerySet

    def test_custom_manager_methods_survive(self):
        "Subclassing MSSQLSafeManager does not displace the rbac managers' own methods."
        from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition

        assert hasattr(DABPermission.objects, "load_remote_objects")
        assert hasattr(DABContentType.objects, "clear_cache")
        assert hasattr(RoleDefinition.objects, "give_creator_permissions")

    def test_mssql_safe_manager_not_serialized_into_migrations(self):
        from ansible_base.lib.mssql.bulk import MSSQLSafeManager

        assert MSSQLSafeManager.use_in_migrations is False


class TestMigrationUtils:
    """give_permissions runs inside migrations, where apps.get_model returns
    historical models with plain managers — the attached MSSQLSafeManager is
    unreachable there, so the migration utils must use the function form."""

    @pytest.mark.django_db
    def test_give_permissions_ignores_conflicts_through_historical_models(self):
        from django.apps import apps as global_apps
        from django.contrib.auth import get_user_model
        from django.db.migrations.state import ProjectState

        from ansible_base.rbac import permission_registry
        from ansible_base.rbac.migrations import _utils
        from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
        from test_app.models import Inventory, Organization

        organization = Organization.objects.create(name='mig-utils-org')
        inventory = Inventory.objects.create(name='mig-utils-inv', organization=organization)
        rd = RoleDefinition.objects.create_from_permissions(
            permissions=['view_inventory'],
            name='mig-utils-view-inv',
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )
        user = get_user_model().objects.create(username='mig-utils-user')
        object_role = rd.give_permission(user, inventory).object_role
        assert RoleUserAssignment.objects.filter(user=user, object_role=object_role).count() == 1

        state_apps = ProjectState.from_apps(global_apps).apps
        historical_manager = state_apps.get_model('dab_rbac', 'RoleUserAssignment').objects
        assert historical_manager.get_queryset().__class__ is not MSSQLSafeQuerySet

        # migration context only ever sees historical instances, so fetch rd and user through it
        historical_rd = state_apps.get_model('dab_rbac', 'RoleDefinition').objects.get(pk=rd.pk)
        historical_user = state_apps.get_model('test_app', 'User').objects.get(pk=user.pk)

        # replaying the assignment through migration context must not raise
        _utils.give_permissions(
            state_apps, historical_rd, users=[historical_user], object_id=object_role.object_id, content_type_id=object_role.content_type_id
        )
        assert RoleUserAssignment.objects.filter(user=user, object_role=object_role).count() == 1
