## BoundedTextField

`BoundedTextField` is a `TextField` that SQL Server can index.

MS SQL Server stores `TextField` as `nvarchar(max)`, and `nvarchar(max)`
cannot participate in an index key. On postgres the field behaves exactly
like a plain `TextField` — column type `text`, unbounded, nothing enforced —
so adopting it changes nothing for postgres deployments today.

On SQL Server the column becomes `nvarchar(sql_server_max_length)`, and the
field attaches a validator (counting UTF-16 code units, matching `nvarchar`
semantics) so that over-length writes fail cleanly at the API layer instead
of hitting the database's truncation error. The validator is vendor-checked
at validation time and is inactive on every other database. Validation runs
wherever field validators run — DRF serializers, model forms, and
`full_clean()`; writes that bypass validators (for example `bulk_create` or
direct ORM saves) still hit the database's truncation error on SQL Server.

### Usage

```python
from ansible_base.lib.fields import BoundedTextField


class MyModel(models.Model):
    name = BoundedTextField(sql_server_max_length=255, db_index=True, unique=True)
    description = models.TextField(blank=True)  # unindexed fields stay unbounded
```

The bound is required (`sql_server_max_length` has no default): it is the
maximum length the column can enforce on SQL Server, and it should be chosen
deliberately:

 - **Tight** where the value's format is known: UUID or integer primary keys
   fit comfortably in 64 (a UUID string is 36 characters); permission
   codenames use 100 for parity with Django's `Permission.codename`.
 - **Roomier** where the text is user-facing and unpredictable but still
   needs an index, e.g. names at 255.
 - Keep bounds on indexed fields at or under `450` to stay below every SQL
   Server index key-size limit (900 bytes clustered, 1700 bytes nonclustered
   on SQL Server 2016+), including in composite keys, which share the budget.
 - Fields that are never indexed or made unique (descriptions, notes) should
   stay plain `TextField`; SQL Server gives them `nvarchar(max)`, which is
   unbounded and fine.

### The `ansible_base.E002` system check

DAB runs a system check (in `manage.py check`, therefore in CI) that raises
an error for any `TextField` carrying `db_index`, `unique`, a
`unique_together` entry, a `UniqueConstraint`, or an `Index` in an
`ansible_base.*` app that is not a `BoundedTextField`. This keeps a future
field from silently becoming un-deployable on SQL Server.

The check is scoped to DAB's own apps. Consumer applications (AWX, gateway,
galaxy_ng) are deliberately unaffected — e.g. AWX's indexed-unique
`singleton_name` will not redden its builds — until they choose to adopt.

The field itself is checked too: `ansible_base.E003` errors on a
`sql_server_max_length` outside 1–4000, the range `nvarchar` can hold.

### Adoption path for components

1. Swap constrained `TextField` definitions to `BoundedTextField` with a
   chosen bound, and rewrite the corresponding migration history in place
   (postgres DDL is unchanged, so this is a no-op for existing deployments
   and `makemigrations --check` stays clean).
2. Once a component's fields are bounded, bounds can be enforced on postgres
   as well — starting at the DRF level (the field's validator propagates to
   serializers automatically) and working down to the database — giving all
   databases the same contract.
