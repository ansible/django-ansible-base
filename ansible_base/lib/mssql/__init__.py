"""MS SQL Server-specific helpers (advisory locks, Service Broker notify params).

Shared, vendor-neutral utilities stay in ansible_base.lib; this package is the
containment home for code that only runs when the database is SQL Server.
See docs/lib/bounded-textfield.md for the field that makes DAB models
deployable on SQL Server.
"""
