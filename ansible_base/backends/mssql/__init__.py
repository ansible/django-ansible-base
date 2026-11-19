"""
Custom Django database backend for Microsoft SQL Server, built on mssql-django.

Set ``DATABASES[...]['ENGINE']`` to ``ansible_base.backends.mssql`` to use it.

The backend adds compatibility behavior around the upstream connection layer:

* Its compiler keeps generated select aliases consistent with Django's
  qualify wrapper under case-sensitive collations.
* It omits SQL Server's ``ISJSON`` check constraint on ``JSONField`` columns,
  allowing encrypted JSON field values to be stored as ciphertext.
"""
