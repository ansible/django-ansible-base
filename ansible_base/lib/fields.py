"""Model fields shared across ansible_base apps."""

from django.core import checks
from django.core.exceptions import ValidationError
from django.db import connection, models
from django.utils.translation import gettext_lazy as _


class SQLServerMaxLengthValidator:
    """Reject values longer than an nvarchar bound, counting UTF-16 code units.

    A standalone callable (not a field method) so that fields inherited from
    abstract bases carry the bound with them, instead of a method bound to the
    abstract base's field instance.
    """

    def __init__(self, sql_server_max_length):
        self.sql_server_max_length = sql_server_max_length

    def __call__(self, value):
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

    def __repr__(self):
        return f'{self.__class__.__name__}(sql_server_max_length={self.sql_server_max_length})'


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
        self.validators.append(SQLServerMaxLengthValidator(sql_server_max_length))

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        if not 1 <= self.sql_server_max_length <= 4000:
            errors.append(
                checks.Error(
                    f'sql_server_max_length must be between 1 and 4000, got {self.sql_server_max_length}',
                    hint='SQL Server nvarchar accepts at most 4000 characters.',
                    obj=self,
                    id='ansible_base.E003',
                )
            )
        return errors

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['sql_server_max_length'] = self.sql_server_max_length
        return name, path, args, kwargs

    def db_type(self, connection):
        if connection.vendor == 'microsoft':
            return f'nvarchar({self.sql_server_max_length})'
        return super().db_type(connection)
