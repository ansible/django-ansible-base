import inspect

from django.db import connection

from ..remote import RemoteObject, StandInPK
from .content_type import DABContentType
from .permission import DABPermission
from .role import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID, RoleTeamAssignment, RoleUserAssignment

__all__ = [
    'DABContentType',
    'RoleDefinition',
    'DABPermission',
    'RoleUserAssignment',
    'RoleTeamAssignment',
    'ObjectRole',
    'RoleEvaluation',
    'RoleEvaluationUUID',
    'get_evaluation_model',
]


def get_evaluation_model(cls):
    if isinstance(cls, RemoteObject) or (inspect.isclass(cls) and issubclass(cls, RemoteObject)):
        # For remote models, we save the pk type in the database specifically
        # for use here, as a logical type string ("uuid", "integer") that may
        # not use this database's spelling of the type. StandInPK converts a
        # recognized type to the database-specific type for comparison; an
        # unrecognized type is left as-is so the RuntimeError below fires
        # instead of silently mapping to the integer evaluation model.
        stand_in_pk = cls._meta.pk
        logical_pk_type = str(stand_in_pk.pk_field_type).strip().lower()
        if logical_pk_type in StandInPK.UUID_FIELD_TYPES or logical_pk_type in StandInPK.INTEGER_FIELD_TYPES:
            pk_db_type = stand_in_pk.db_type(connection)
        else:
            pk_db_type = logical_pk_type
    else:
        pk_field = cls._meta.pk
        # For proxy models, including django-polymorphic, use the id field from parent table
        # we accomplish this by inspecting the raw database type of the field
        pk_db_type = pk_field.db_type(connection)

    for eval_cls in (RoleEvaluation, RoleEvaluationUUID):
        if pk_db_type == eval_cls._meta.get_field('object_id').db_type(connection):
            return eval_cls
    # HACK: integer pk caching is handled by same model for now, better to use default pk type later
    # the integer unsigned case happens in AWX in sqlite3 specifically
    if pk_db_type in ('bigint', 'integer', 'integer unsigned'):
        return RoleEvaluation

    if connection.vendor == 'sqlite' and pk_db_type == 'uuid':
        return RoleEvaluationUUID

    raise RuntimeError(f'Model {cls._meta.model_name} primary key type of {type(cls._meta.pk)} (db type {pk_db_type}) is not supported')
