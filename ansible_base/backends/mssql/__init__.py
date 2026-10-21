"""
Custom MS SQL Server database backend with TextField-to-CharField conversion.

This backend extends mssql-django to automatically convert TextField definitions
to CharField when they have db_index=True, unique=True, or are used in constraints.
This enables MS SQL Server compatibility without duplicating migration files.
"""
