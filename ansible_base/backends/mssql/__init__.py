"""
Custom Django database backend for Microsoft SQL Server, built on mssql-django.

Set ``DATABASES[...]['ENGINE']`` to ``ansible_base.backends.mssql`` to use it.

The backend adds compatibility behavior around the upstream connection layer:

* Its schema editor converts indexed or constrained ``TextField`` columns to
  bounded ``CharField`` columns so SQL Server can create the corresponding
  indexes and unique constraints, without changing migration files.
* Its cursor converts Python UUID parameters to 32-character hexadecimal
  strings for pyodbc.
* It omits SQL Server's ``ISJSON`` check constraint on ``JSONField`` columns,
  allowing encrypted JSON field values to be stored as ciphertext.
"""
