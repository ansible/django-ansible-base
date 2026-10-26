import inspect

from django.db import connection

from ..remote import RemoteObject
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
    if isinstance(cls, RemoteObject):
        # For remote models, we save the pk type in the database specifically for use here
        pk_db_type = cls.content_type.pk_field_type
    elif inspect.isclass(cls) and issubclass(cls, RemoteObject):
        # Weirdness when passed a remote class but not a remote object, get type first
        pk_db_type = cls.get_ct_from_type().pk_field_type
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
