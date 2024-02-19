# activitystream

The django-ansible-base `activitystream` app provides an audit log of changes
that happen to models within the system.

## Consumer Docs

To make use of `activitystream` in your application, first add
`ansible_base.activitystream` to your `INSTALLED_APPS`.

Now in your models you can:

```python
from ansible_base.activitystream.models import AuditableModel
```

... and make your model inherit from `AuditableModel`. In theory, this is all
that is required. When your application starts up, `activitystream` will ask
Django to list all the models it knows about. It will then filter this list for
ones that inherit from `AuditableModel` and call the
`AuditableModel::connect_signals` class method which registers the appropriate
signals.

You can exclude fields from being included in the changes logged by
`activitystream` by setting the `activity_stream_excluded_field_names` class
variable in your model.

### What changes look like

The main activity stream model is
`ansible_base.activitystream.models.entry.Entry`, and changes are stored in its
`changes` field, which is a `JSONField`.

The JSON stored in this field is that of a `dict` returned by
the function `ansible_base.lib.utils.models.diff`. Ultimately what we store will
be a dictionary with three entries, `added_fields`, `removed_fields`, and
`changed_fields`.

The structure of these fields is as follows:

`added_fields`: This is a dictionary, with each entry being a field that that
was added from one model to another. In the context of the activity stream,
every "creation" event comes from the `None` model, meaning every field is a new
field. So for creations, all fields are stored in `added_fields`. Behind the
scenes, the `diff()` function allows for comparing different *types* of models,
and so in theory it's possible to have changes in `changed_fields` for some
fields and fields added in `added_fields` for other fields if those fields are
not defined in the first ("old") model. But again, in the context of activity
stream, we are always comparing the same kinds of model.

`deleted_fields`: This is very similar to `added_fields`. In the context
of the activity stream, a record being deleted is kind of the same as turning it
into the `None` model, and all fields are stored in `deleted_fields`. Like in
`added_fields`, the `diff()` function could use this if comparing two different
kinds of models, but in the context of the activity stream, that doesn't happen.

`changed_fields`: This is a dictionary which has field names as keys and
2-tuples as values in the form (old_value, new_value).


## Dev Docs

The way this works is by making use of Django signals. At a high level, when
certain events happen, signal receivers (callback functions) that are connected
to listen for those events can be called automatically by the Django framework.
We make use of this listening to `post_save`, `pre_save`, and `pre_delete`.

Note that we make use of Django's
[contenttypes](https://docs.djangoproject.com/en/5.0/ref/contrib/contenttypes/)
framework and thus we store a generic foreign key to the instance of the model
being acted on.

### create

When a new record (instance of a model) is created and saved, we want to act on
`post_save`. The reason for this is that, if we used `pre_save` which is called
earlier, we wouldn't yet have a primary key/id to reference the object in the
activity stream.

Using
[`post_save`](https://docs.djangoproject.com/en/5.0/ref/signals/#post-save)
also passes us a `created` argument so we can tell if a new record was created
or if an existing one was being updated. For our purposes, if a record is _not_
being created, we don't want to do anything in `post_save`. For updates to
existing records, keep reading.

### update

For updates to existing records, we need to take a diff of the changes. So we
need to be able to access the _current_ version of the record, *before* the new
one is saved. For this, we can use
[`pre_save`](https://docs.djangoproject.com/en/5.0/ref/signals/#pre-save) which
is called before the update is saved to the database. This gives us a chance to
grab a copy of the current record compare it with the record that is about to be
saved, and store those differences in the activity stream.

### delete

For deleting, we use
[`pre_delete`](https://docs.djangoproject.com/en/5.0/ref/signals/#pre-delete).

### (dis)association

For associating and disassociating m2m fields, we use
[`m2m_changed`](https://docs.djangoproject.com/en/5.0/ref/signals/#m2m-changed).
