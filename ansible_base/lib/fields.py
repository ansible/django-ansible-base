"""Model fields shared across ansible_base apps."""

from django.core.exceptions import ValidationError
from django.db import connection, models
from django.utils.translation import gettext_lazy as _


class BoundedTextField(models.TextField):
    """TextField that SQL Server can index.

    Postgres: ``text``; nothing enforced anywhere, exactly as today.
    SQL Server: ``nvarchar(sql_server_max_length)``; the column type is the only hard
    limit, mirrored by a validator so API writes fail cleanly instead of hitting the
    database's truncation error.
    """

    def __init__(self, *args, sql_server_max_length, **kwargs):
        self.sql_server_max_length = sql_server_max_length
        super().__init__(*args, **kwargs)
        self.validators.append(self._validate_sql_server_length)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['sql_server_max_length'] = self.sql_server_max_length
        return name, path, args, kwargs

    def db_type(self, connection):
        # Note: this method's `connection` parameter shadows the module-level import;
        # the validator below reads the module-level one at call time.
        if connection.vendor == 'microsoft':
            return f'nvarchar({self.sql_server_max_length})'
        return super().db_type(connection)

    def _validate_sql_server_length(self, value):
        if not value or connection.vendor != 'microsoft':
            return
        # nvarchar length is UTF-16 code units: surrogate pairs count as two
        length = len(value.encode('utf-16-le', errors='surrogatepass')) // 2
        if length > self.sql_server_max_length:
            raise ValidationError(
                _('Ensure this value has at most %(limit)d UTF-16 code units on MS SQL Server (it has %(length)d).'),
                code='max_length',
                params={'limit': self.sql_server_max_length, 'length': length},
            )
