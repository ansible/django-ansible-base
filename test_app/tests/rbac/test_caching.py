"""Tests for ansible_base.rbac.caching — specifically the concurrency guards:
_is_stale_objectrole_fk, _safe_m2m_add, _safe_bulk_create_evaluations, and the
insert ordering and deadlock retry of the RoleEvaluation bulk insert.
"""

import threading
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError, OperationalError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.caching import (
    DEADLOCK_RETRIES,
    _evaluation_sort_key,
    _is_deadlock,
    _is_stale_objectrole_fk,
    _safe_bulk_create_evaluations,
    _safe_m2m_add,
)
from ansible_base.rbac.models import RoleEvaluation, RoleEvaluationUUID
from test_app.models import Inventory

# ---------------------------------------------------------------------------
# Helpers to build mock psycopg-style exceptions
# ---------------------------------------------------------------------------


def _make_integrity_error(sqlstate=None, message='some error', use_pgcode=False):
    """Build a Django IntegrityError wrapping a fake DB-level cause."""
    cause = Exception(message)
    if use_pgcode:
        cause.pgcode = sqlstate
    else:
        cause.sqlstate = sqlstate
    exc = IntegrityError(message)
    exc.__cause__ = cause
    return exc


def _make_objectrole_fk_error(use_pgcode=False):
    """Build an IntegrityError that mimics a Postgres FK violation on dab_rbac_objectrole."""
    return _make_integrity_error(
        sqlstate='23503',
        message=(
            'insert or update on table "dab_rbac_objectrole_provides_teams" violates '
            'foreign key constraint "dab_rbac_objectrole_p_objectrole_id_abc123_fk_dab_rbac_o"\n'
            'DETAIL:  Key (objectrole_id)=(999) is not present in table "dab_rbac_objectrole".'
        ),
        use_pgcode=use_pgcode,
    )


def _make_operational_error(sqlstate, use_pgcode=False):
    """Build a Django OperationalError wrapping a fake DB-level cause."""
    cause = Exception('deadlock detected' if sqlstate == '40P01' else 'some error')
    if use_pgcode:
        cause.pgcode = sqlstate
    else:
        cause.sqlstate = sqlstate
    exc = OperationalError(str(cause))
    exc.__cause__ = cause
    return exc


@contextmanager
def _noop_atomic(*args, **kwargs):
    """Stand-in for transaction.atomic() that skips real savepoint SQL."""
    yield


# ---------------------------------------------------------------------------
# _is_stale_objectrole_fk
# ---------------------------------------------------------------------------


class TestIsStaleObjectroleFk:
    def test_returns_true_for_objectrole_fk_violation_psycopg3(self):
        exc = _make_objectrole_fk_error(use_pgcode=False)
        assert _is_stale_objectrole_fk(exc) is True

    def test_returns_true_for_objectrole_fk_violation_psycopg2(self):
        exc = _make_objectrole_fk_error(use_pgcode=True)
        assert _is_stale_objectrole_fk(exc) is True

    def test_returns_false_when_no_cause(self):
        exc = IntegrityError('bare error')
        assert _is_stale_objectrole_fk(exc) is False

    def test_returns_false_for_unique_constraint_violation(self):
        exc = _make_integrity_error(
            sqlstate='23505',
            message='duplicate key value violates unique constraint "dab_rbac_objectrole_one_object_role"',
        )
        assert _is_stale_objectrole_fk(exc) is False

    def test_returns_false_for_fk_violation_on_different_table(self):
        exc = _make_integrity_error(
            sqlstate='23503',
            message='Key (team_id)=(42) is not present in table "main_team".',
        )
        assert _is_stale_objectrole_fk(exc) is False

    def test_returns_false_for_check_constraint(self):
        exc = _make_integrity_error(
            sqlstate='23514',
            message='new row violates check constraint "positive_id"',
        )
        assert _is_stale_objectrole_fk(exc) is False

    def test_returns_false_for_sqlite_fk_error(self):
        """SQLite FK errors have no sqlstate/pgcode — should not be suppressed."""
        cause = Exception('FOREIGN KEY constraint failed')
        exc = IntegrityError('FOREIGN KEY constraint failed')
        exc.__cause__ = cause
        assert _is_stale_objectrole_fk(exc) is False

    def test_returns_false_when_sqlstate_is_none(self):
        cause = Exception('some random db error')
        exc = IntegrityError('some random db error')
        exc.__cause__ = cause
        assert _is_stale_objectrole_fk(exc) is False

    def test_returns_true_for_role_evaluation_fk_violation(self):
        """The role_id FK on dab_rbac_roleevaluation also references dab_rbac_objectrole."""
        exc = _make_integrity_error(
            sqlstate='23503',
            message=(
                'insert or update on table "dab_rbac_roleevaluation" violates '
                'foreign key constraint "dab_rbac_roleevaluat_role_id_abc_fk_dab_rbac_o"\n'
                'DETAIL:  Key (role_id)=(42) is not present in table "dab_rbac_objectrole".'
            ),
        )
        assert _is_stale_objectrole_fk(exc) is True


# ---------------------------------------------------------------------------
# _safe_m2m_add
#
# team.member_roles is a Django M2M descriptor that returns a fresh manager
# each access, so we cannot patch it on a real Team instance.  Instead these
# tests use a MagicMock team whose .member_roles.add is fully controllable,
# and mock transaction.atomic to skip real savepoint SQL (the mock-raised
# IntegrityError never touches the DB).
# ---------------------------------------------------------------------------


class TestSafeM2mAdd:
    @pytest.mark.django_db
    def test_happy_path_adds_ids(self, team, member_rd, rando):
        """When no race occurs, compute_team_member_roles (which calls
        _safe_m2m_add internally) works end-to-end with real DB objects."""
        from ansible_base.rbac.caching import compute_team_member_roles

        member_rd.give_permission(rando, team)
        compute_team_member_roles()
        assert team.member_roles.exists()

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    def test_retries_on_stale_fk(self, mock_or_qs):
        """First add() hits a stale-FK IntegrityError, retry succeeds with filtered IDs."""
        mock_or_qs.filter.return_value.values_list.return_value = [1]
        team = MagicMock()
        call_count = 0

        def flaky_add(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_objectrole_fk_error()

        team.member_roles.add.side_effect = flaky_add
        _safe_m2m_add(team, {1, 9999})
        assert call_count == 2
        mock_or_qs.filter.assert_called_once()

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    @patch('ansible_base.rbac.caching.logger')
    def test_logs_warning_on_persistent_fk_error(self, mock_logger, mock_or_qs):
        """Both attempts fail with stale-FK error — logs warning, does not raise."""
        mock_or_qs.filter.return_value.values_list.return_value = [1]
        team = MagicMock()
        team.member_roles.add.side_effect = _make_objectrole_fk_error()

        _safe_m2m_add(team, {1})
        mock_logger.warning.assert_called_once()
        assert 'Persistent IntegrityError' in mock_logger.warning.call_args[0][0]

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    def test_reraises_non_fk_integrity_error(self):
        """A unique-constraint IntegrityError is re-raised, not swallowed."""
        team = MagicMock()
        team.member_roles.add.side_effect = _make_integrity_error(sqlstate='23505', message='duplicate key')
        with pytest.raises(IntegrityError, match='duplicate key'):
            _safe_m2m_add(team, {1})

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    def test_retry_reraises_non_fk_integrity_error(self, mock_or_qs):
        """First call hits stale FK (retries), second call hits a different error — re-raised."""
        mock_or_qs.filter.return_value.values_list.return_value = [1]
        team = MagicMock()
        stale_exc = _make_objectrole_fk_error()
        unique_exc = _make_integrity_error(sqlstate='23505', message='duplicate key')
        call_count = 0

        def switching_add(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise stale_exc
            raise unique_exc

        team.member_roles.add.side_effect = switching_add
        with pytest.raises(IntegrityError, match='duplicate key'):
            _safe_m2m_add(team, {1})

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    def test_skips_retry_when_no_valid_ids_remain(self, mock_or_qs):
        """After filtering, no IDs remain — second add() is never called."""
        mock_or_qs.filter.return_value.values_list.return_value = []
        team = MagicMock()
        exc = _make_objectrole_fk_error()
        team.member_roles.add.side_effect = exc

        _safe_m2m_add(team, {9999})
        team.member_roles.add.assert_called_once()


# ---------------------------------------------------------------------------
# _safe_bulk_create_evaluations
# ---------------------------------------------------------------------------


class TestSafeBulkCreateEvaluations:
    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    def test_noop_on_empty_list(self):
        """Empty evaluations list returns immediately without DB calls."""
        with patch.object(RoleEvaluation.objects, 'bulk_create') as mock_bc:
            _safe_bulk_create_evaluations(RoleEvaluation, [], False)
            mock_bc.assert_not_called()

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    def test_happy_path_calls_bulk_create(self):
        """When no error, bulk_create is called once."""
        evals = [MagicMock(role_id=1, object_id=1)]
        with patch.object(RoleEvaluation.objects, 'bulk_create') as mock_bc:
            _safe_bulk_create_evaluations(RoleEvaluation, evals, True)
            mock_bc.assert_called_once_with(evals, ignore_conflicts=True)

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    def test_retries_on_stale_fk(self, mock_or_qs):
        """First bulk_create hits stale FK, retry succeeds after filtering."""
        mock_or_qs.filter.return_value.values_list.return_value = [1]
        eval1 = MagicMock(role_id=1, object_id=10)
        eval2 = MagicMock(role_id=2, object_id=20)
        exc = _make_objectrole_fk_error()
        call_count = 0

        def flaky_bulk_create(objs, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise exc

        with patch.object(RoleEvaluation.objects, 'bulk_create', side_effect=flaky_bulk_create):
            _safe_bulk_create_evaluations(RoleEvaluation, [eval1, eval2], True)

        assert call_count == 2

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    @patch('ansible_base.rbac.caching.logger')
    def test_logs_warning_on_persistent_fk_error(self, mock_logger, mock_or_qs):
        """Both attempts fail with stale-FK — logs warning, does not raise."""
        mock_or_qs.filter.return_value.values_list.return_value = [1]
        eval1 = MagicMock(role_id=1, object_id=10)
        exc = _make_objectrole_fk_error()

        with patch.object(RoleEvaluation.objects, 'bulk_create', side_effect=exc):
            _safe_bulk_create_evaluations(RoleEvaluation, [eval1], False)
            mock_logger.warning.assert_called_once()
            assert 'Persistent IntegrityError' in mock_logger.warning.call_args[0][0]

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    def test_reraises_non_fk_integrity_error(self):
        """A unique-constraint IntegrityError propagates."""
        eval1 = MagicMock(role_id=1, object_id=10)
        exc = _make_integrity_error(sqlstate='23505', message='duplicate key')

        with patch.object(RoleEvaluation.objects, 'bulk_create', side_effect=exc):
            with pytest.raises(IntegrityError, match='duplicate key'):
                _safe_bulk_create_evaluations(RoleEvaluation, [eval1], False)

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    def test_retry_reraises_non_fk_integrity_error(self, mock_or_qs):
        """First call hits stale FK, retry hits different error — re-raised."""
        mock_or_qs.filter.return_value.values_list.return_value = [1]
        eval1 = MagicMock(role_id=1, object_id=10)
        stale_exc = _make_objectrole_fk_error()
        unique_exc = _make_integrity_error(sqlstate='23505', message='duplicate key')
        call_count = 0

        def switching_bulk_create(objs, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise stale_exc
            raise unique_exc

        with patch.object(RoleEvaluation.objects, 'bulk_create', side_effect=switching_bulk_create):
            with pytest.raises(IntegrityError, match='duplicate key'):
                _safe_bulk_create_evaluations(RoleEvaluation, [eval1], False)

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    def test_filters_out_stale_role_ids(self, mock_or_qs):
        """After first failure, only evaluations with still-valid role_ids are retried."""
        mock_or_qs.filter.return_value.values_list.return_value = [1]
        eval_good = MagicMock(role_id=1, object_id=10)
        eval_stale = MagicMock(role_id=999, object_id=20)
        exc = _make_objectrole_fk_error()

        retried_evals = []
        call_count = 0

        def flaky_then_capture(objs, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise exc
            retried_evals.extend(objs)

        with patch.object(RoleEvaluation.objects, 'bulk_create', side_effect=flaky_then_capture):
            _safe_bulk_create_evaluations(RoleEvaluation, [eval_good, eval_stale], True)

        assert retried_evals == [eval_good]

    @patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
    @patch('ansible_base.rbac.caching.ObjectRole.objects')
    def test_skips_retry_when_no_valid_ids_remain(self, mock_or_qs):
        """After filtering, no evaluations remain — second bulk_create is never called."""
        mock_or_qs.filter.return_value.values_list.return_value = []
        eval1 = MagicMock(role_id=999, object_id=10)
        exc = _make_objectrole_fk_error()
        call_count = 0

        def counting_bulk_create(objs, **kwargs):
            nonlocal call_count
            call_count += 1
            raise exc

        with patch.object(RoleEvaluation.objects, 'bulk_create', side_effect=counting_bulk_create):
            _safe_bulk_create_evaluations(RoleEvaluation, [eval1], False)

        assert call_count == 1


# ---------------------------------------------------------------------------
# RoleEvaluation insert order and deadlock retry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('model', [RoleEvaluation, RoleEvaluationUUID])
def test_sort_key_matches_unique_constraint(model):
    """The sort key must follow the column order of the unique index the inserts lock on."""
    constraint = next(c for c in model._meta.constraints if c.name.startswith('one_entry_per_object_permission_and_role'))
    columns = [model._meta.get_field(name).attname for name in constraint.fields]
    evaluation = model(codename='view_inventory', content_type_id=7, object_id=uuid4() if model is RoleEvaluationUUID else 42, role_id=3)
    assert _evaluation_sort_key(evaluation) == tuple(getattr(evaluation, column) for column in columns)


@pytest.mark.parametrize('model, object_ids', [(RoleEvaluation, [3, 1, 2]), (RoleEvaluationUUID, [uuid4(), uuid4(), uuid4()])])
@patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
def test_bulk_insert_is_in_unique_index_order(model, object_ids):
    """Whatever order the evaluations are collected in, they are inserted in unique-index order."""
    evaluations = [
        model(codename=codename, content_type_id=ct_id, object_id=object_id, role_id=role_id)
        for role_id in (5, 4)
        for codename in ('view_inventory', 'change_inventory')
        for ct_id in (2, 1)
        for object_id in object_ids
    ]
    with patch.object(model.objects, 'bulk_create') as mock_bc:
        _safe_bulk_create_evaluations(model, evaluations, True)
    inserted = [_evaluation_sort_key(e) for e in mock_bc.call_args.args[0]]
    assert inserted == sorted(_evaluation_sort_key(e) for e in evaluations)


@pytest.mark.parametrize(
    'sqlstate, use_pgcode, expected',
    [('40P01', False, True), ('40P01', True, True), ('55P03', False, False), (None, False, False)],
)
def test_is_deadlock(sqlstate, use_pgcode, expected):
    assert _is_deadlock(_make_operational_error(sqlstate, use_pgcode=use_pgcode)) is expected


@pytest.mark.parametrize(
    'errors, expected_calls, raises',
    [
        pytest.param([_make_operational_error('40P01')], 2, False, id='deadlock-then-success'),
        pytest.param([_make_operational_error('40P01')] * (DEADLOCK_RETRIES + 1), DEADLOCK_RETRIES + 1, True, id='persistent-deadlock'),
        pytest.param([_make_operational_error('55P03')], 1, True, id='other-operational-error'),
    ],
)
@patch('ansible_base.rbac.caching.time.sleep')
@patch('ansible_base.rbac.caching.transaction.atomic', _noop_atomic)
def test_bulk_insert_deadlock_retry(mock_sleep, errors, expected_calls, raises):
    """A deadlock victim's insert runs again, up to DEADLOCK_RETRIES times; other errors are raised at once."""
    remaining = list(errors)

    def bulk_create(objs, **kwargs):
        if remaining:
            raise remaining.pop(0)

    evaluations = [MagicMock(role_id=1, object_id=10)]
    with patch.object(RoleEvaluation.objects, 'bulk_create', side_effect=bulk_create) as mock_bc:
        if raises:
            with pytest.raises(OperationalError):
                _safe_bulk_create_evaluations(RoleEvaluation, evaluations, True)
        else:
            _safe_bulk_create_evaluations(RoleEvaluation, evaluations, True)
    assert mock_bc.call_count == expected_calls


@pytest.mark.django_db(transaction=True)
def test_concurrent_gap_heals_in_reversed_order_do_not_deadlock(organization, rando, org_inv_rd):
    """Two transactions healing the same gap from opposite ends insert in the same order, so neither deadlocks.

    Unsorted, the reversed lists meet in the middle and each waits on the other's
    uncommitted rows, which Postgres resolves by killing one of them.
    """
    if connection.vendor != 'postgresql':
        pytest.skip('Row-level lock waits need Postgres')
    role = org_inv_rd.give_permission(rando, organization).object_role
    RoleEvaluation.objects.filter(role=role).delete()
    ct_id = permission_registry.content_type_model.objects.get_for_model(Inventory).id
    rows = [(codename, object_id) for object_id in range(1, 3001) for codename in ('view_inventory', 'change_inventory')]
    barrier = threading.Barrier(2)
    errors = []

    def heal(ordered_rows):
        try:
            with transaction.atomic():
                barrier.wait(timeout=30)
                evaluations = [
                    RoleEvaluation(codename=codename, content_type_id=ct_id, object_id=object_id, role_id=role.id) for codename, object_id in ordered_rows
                ]
                _safe_bulk_create_evaluations(RoleEvaluation, evaluations, True)
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    with patch('ansible_base.rbac.caching.logger') as mock_logger:
        threads = [threading.Thread(target=heal, args=(rows,)), threading.Thread(target=heal, args=(rows[::-1],))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

    assert errors == []
    assert not [call for call in mock_logger.warning.call_args_list if 'Deadlock' in call.args[0]]
    assert RoleEvaluation.objects.filter(role=role).count() == len(rows)
