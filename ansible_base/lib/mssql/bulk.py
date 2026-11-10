"""Transparent MS SQL Server bulk-write compatibility for Django QuerySets.

SQL Server (via mssql-django) lacks native ``ignore_conflicts`` support for
``bulk_create``, and multi-row inserts cannot always return generated primary
keys. This module provides ``MSSQLSafeQuerySet``, a QuerySet whose
``bulk_create``/``bulk_update`` fall back to batch-then-per-row inserts and
batch clamping on SQL Server while delegating to stock Django everywhere else.

Attach ``MSSQLSafeManager`` (built from this QuerySet) as ``objects`` on the
shared abstract model bases so application code keeps writing plain ORM calls;
``bulk_create()`` below is the same logic in function form, for migration
utilities only — Django swaps historical models' managers for a plain
``Manager``, so migrations cannot reach the queryset override.
"""

import logging

from django.db import DEFAULT_DB_ALIAS, IntegrityError, connections, models, router, transaction

from ansible_base.lib.mssql.params import SQL_SERVER_MAX_QUERY_PARAMETERS, SQL_SERVER_QUERY_PARAMETER_HEADROOM

logger = logging.getLogger(__name__)

# Rows per savepoint-batched fallback when the backend cannot return rows from
# a multi-row insert (ported from the original SQL Server support work).
_SAVEPOINT_FALLBACK_BATCH = 50


class MSSQLSafeQuerySet(models.QuerySet):
    """QuerySet with SQL Server-safe bulk_create/bulk_update; stock behavior on other vendors."""

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=None,
        unique_fields=None,
        update_fields=None,
    ):
        objs = list(objs)
        connection = connections[self.db]
        if connection.vendor != "microsoft" or update_conflicts is not None:
            # Other vendors — and update_conflicts, which mssql-django does not
            # support — are Django's business: delegate and let Django's own
            # NotSupportedError surface unchanged.
            return self._delegate_bulk_create(
                objs,
                batch_size=batch_size,
                ignore_conflicts=ignore_conflicts,
                update_conflicts=update_conflicts,
                unique_fields=unique_fields,
                update_fields=update_fields,
            )
        if ignore_conflicts and not connection.features.supports_ignore_conflicts:
            return self._bulk_create_ignoring_conflicts(objs, batch_size)
        if not ignore_conflicts and not connection.features.can_return_rows_from_bulk_insert:
            return self._bulk_create_with_savepoints(objs)
        return self._delegate_bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            unique_fields=unique_fields,
            update_fields=update_fields,
        )

    def _delegate_bulk_create(self, objs, *, batch_size, ignore_conflicts, update_conflicts=None, unique_fields=None, update_fields=None):
        "Forward to stock QuerySet.bulk_create, passing conflict kwargs through only when set."
        kwargs = {"batch_size": batch_size, "ignore_conflicts": ignore_conflicts}
        if update_conflicts is not None:
            kwargs.update(update_conflicts=update_conflicts, unique_fields=unique_fields, update_fields=update_fields)
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        connection = connections[self.db]
        if connection.vendor != "microsoft":
            return super().bulk_update(objs, fields, batch_size=batch_size)
        if batch_size is not None:
            # mssql-django already clamps its own default (batch_size=None) via
            # DatabaseOperations.bulk_batch_size; only an explicit caller-chosen
            # batch can exceed SQL Server's parameter ceiling.
            max_batch = (SQL_SERVER_MAX_QUERY_PARAMETERS - SQL_SERVER_QUERY_PARAMETER_HEADROOM) // max(1, len(fields))
            batch_size = min(batch_size, max_batch)
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def _bulk_create_ignoring_conflicts(self, objs, batch_size):
        """Insert ignoring conflicts without native support: try the batch, retry rows that conflict."""
        connection = connections[self.db]
        created = []
        if connection.features.can_return_rows_from_bulk_insert:
            savepoint_id = transaction.savepoint(using=self.db)
            try:
                created = super().bulk_create(objs, batch_size=batch_size, ignore_conflicts=False)
                transaction.savepoint_commit(savepoint_id, using=self.db)
                return created
            except IntegrityError as exc:
                logger.warning("bulk_create batch conflicted for %s: %s", self.model.__name__, exc)
                connection.needs_rollback = False
                transaction.savepoint_rollback(savepoint_id, using=self.db)
            except BaseException:
                transaction.savepoint_rollback(savepoint_id, using=self.db)
                raise
        for obj in objs:
            savepoint_id = transaction.savepoint(using=self.db)
            try:
                created.append(self._bulk_insert_one(obj))
                transaction.savepoint_commit(savepoint_id, using=self.db)
            except IntegrityError as exc:
                logger.warning("bulk_create row conflicted for %s: %s", self.model.__name__, exc)
                connection.needs_rollback = False
                transaction.savepoint_rollback(savepoint_id, using=self.db)
            except BaseException:
                transaction.savepoint_rollback(savepoint_id, using=self.db)
                raise
        return created

    def _bulk_create_with_savepoints(self, objs):
        """Insert one row at a time in batched savepoints when generated IDs are needed.

        Used when the backend cannot return rows from a multi-row insert (a
        user opting out of ``OPTIONS['return_rows_bulk_insert']``).
        """
        created = []
        for start in range(0, len(objs), _SAVEPOINT_FALLBACK_BATCH):
            batch = objs[start : start + _SAVEPOINT_FALLBACK_BATCH]
            savepoint_id = transaction.savepoint(using=self.db)
            try:
                for obj in batch:
                    created.append(self._bulk_insert_one(obj))
                transaction.savepoint_commit(savepoint_id, using=self.db)
            except BaseException:
                transaction.savepoint_rollback(savepoint_id, using=self.db)
                raise
        return created

    def _bulk_insert_one(self, obj):
        """Insert one object without calling its model save override or save signals."""
        self._prepare_for_bulk_create([obj])
        opts = self.model._meta
        fields = [field for field in opts.concrete_fields if not field.generated]
        if not obj._is_pk_set():
            fields = [field for field in fields if not isinstance(field, models.AutoField)]

        returning_fields = opts.db_returning_fields
        returned_rows = self._insert([obj], fields, using=self.db, returning_fields=returning_fields)
        for returned_row in returned_rows:
            for value, field in zip(returned_row, returning_fields):
                setattr(obj, field.attname, value)
        obj._state.db = self.db
        obj._state.adding = False
        return obj


MSSQLSafeManager = models.Manager.from_queryset(MSSQLSafeQuerySet)
# Never serialize this manager into migration files (historical models keep a
# plain Manager; migration code uses the bulk_create function form instead).
MSSQLSafeManager.use_in_migrations = False


def bulk_create(model, objs, *, ignore_conflicts=False, using=None):
    """Vendor-safe bulk_create for migration utilities.

    Migration historical models carry a plain Manager, so they cannot reach
    ``MSSQLSafeQuerySet`` through ``Model.objects``; this function applies the
    same dispatch by constructing the queryset directly. Application code
    should never call this — use ``Model.objects.bulk_create(...)``.
    """
    if using is None:
        using = router.db_for_write(model) or DEFAULT_DB_ALIAS
    return MSSQLSafeQuerySet(model=model, using=using).bulk_create(objs, ignore_conflicts=ignore_conflicts)
