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

#### Excluding Fields

You can exclude fields from being included in the changes logged by
`activitystream` by setting the `activity_stream_excluded_field_names` class
variable in your model.

#### Limiting Fields

You can specify a list of fields to include in activity stream entries for a
model, if you don't want all fields to be included by default. In this way you
can *limit* activity stream entries to the provided list of fields. Do this by
setting the `activity_stream_limit_field_names` class variable in your model.

### What activity stream entries look like

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

**Note about encrypted fields**: The following fields are considered sensitive
and their values (even hashed) are not saved in activity stream entries:

- Fields listed in `encrypted_fields` of a `CommonModel` subclass
- The `password` field of any `AbstractUser` subclass
- Any model fields wrapped with `ansible_base.lib.utils.models.prevent_search()`

**Note about types**: In order to provide filtering and searching, field values
in the JSON blob are always coerced to a string. See the section about searching
in the developer docs below for implementation details. In short: At
serialization time, values are converted to the expected types based on the
model field from which they originated. So we **present** the correct types, but
**store** strings in the database.


### URLs

This feature includes URLs which you will get if you are using
[dynamic urls](../Installation.md).

If you want to manually add the URLs without dynamic urls, add the following to
your `urls.py`:

```
from ansible_base.activitystream import urls as activity_stream_urls
urlpatterns = [
    ...
    path('api/v1/', include(activity_stream_urls.api_version_urls)),
    ...
]
```


### Permissions

The activity stream can rely on the RBAC app to control permissions pertaining
to who can see activity stream entries via the API.

If the RBAC app is **not** being used, then only superusers can access the
stream.


### Filtering

You can search/filter the activity stream using the normal DRF filtering
technique of providing querystring parameters.

For example, given the following:

```json
{
    "id": 1,
    "url": "",
    "related": {
        "created_by": "/api/v1/users/1/"
    },
    "summary_fields": {
        "created_by": {
            "id": 1,
            "username": "_system",
            "first_name": "",
            "last_name": ""
        },
        "content_object": {
            "id": 2,
            "username": "admin",
            "first_name": "",
            "last_name": ""
        }
    },
    "created": "2024-04-09T15:38:33.490777Z",
    "created_by": 1,
    "operation": "create",
    "changes": {
        "added_fields": {
            "id": 2,
            "email": "admin@stuff.invalid",
            "created": "2024-04-09T15:38:33.480352Z",
            "is_staff": true,
            "modified": "2024-04-09T15:38:33.480341Z",
            "password": "$encrypted$",
            "username": "admin",
            "is_active": true,
            "last_name": "",
            "created_by": 1,
            "first_name": "",
            "last_login": null,
            "date_joined": "2024-04-09T15:38:33.356102Z",
            "modified_by": 1,
            "is_superuser": true,
            "created_by_id": 1,
            "modified_by_id": 1
        },
        "changed_fields": {},
        "removed_fields": {}
    },
    "content_type": 17,
    "object_id": "2",
    "related_content_type": null,
    "related_object_id": null,
    "content_type_model": "user",
    "related_content_type_model": null
}
```

... you can filter from the `activitystream-list` URL by adding
`?operation__exact=create&changes__added_fields__email=admin@stuff.invalid`
to the URL.

In the case of `changed_fields` where the values of the fields are size-2
arrays, you can index into them using `__0__` and `__1__`. For example, to get
all activity stream entries where the `weather` field was changed to `sunny`,
you can use `?changes__changed_fields__weather__1__exact=sunny`.


## Dev Docs

The way this works is by making use of Django signals. At a high level, when
certain events happen, signal receivers (callback functions) that are connected
to listen for those events can be called automatically by the Django framework.
We make use of this listening to `post_save`, `pre_save`, and `pre_delete`.

Note that we make use of Django's
[contenttypes](https://docs.djangoproject.com/en/5.0/ref/contrib/contenttypes/)
framework and thus we store a generic foreign key to the instance of the model
being acted on.

The values of all fields (ie. the values of the dictionaries in `changes`) are
coerced to strings before they are saved in the database. This is done by the
`diff` utility function (as called by our signals with
`all_values_as_strings=True`). The reason for this is to allow filtering
(described above) to work. All filter parameters from the querystring come in as
strings and trying to compare them against non-string values stored in the JSON
blob doesn't work. Therefore, we store the values as strings, and then at
serialization time we convert the values back to their expected types, based on
the field the value came from, using `Field#to_python`.

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
