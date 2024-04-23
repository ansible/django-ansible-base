# Associative Resource Router

django-ansible-base provides an `AssociationResourceRouter` which will auto-construct /associate and /disassociate endpoints for related ManyToMany fields for your models.

To use this router simply do the following:
```
from ansible_base.lib.routers import AssociationResourceRouter

router = AssociationResourceRouter()

router.register(
    r'users',
    views.UserViewSet,
)

urlpatterns = [
    path('api/service/v1/', include(router.urls)),
]
```

This would create an endpoint called `users` in your application with all of the post/patch/put/delete/get endpoints as defined by the UserViewSet.

# Related fields

The AssociationResourceRouter can also handle many-to-many or reverse foreign key (one-to_many) fields by adding a `related_views` field to the register function. For example, consider this register command:
```
router.register(
    r'users',
    views.UserViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'teams'),
        'organizations': (views.OrganizationViewSet, 'organizations'),
    },
)
```

The router interrogates model of the queryset from the parent view along with the model of the query set from the related view and determines if the relation is a many-to-many or a reverse foreign key.

Related views are expressed in the following format:

```
    '<entry in API related field>': (<ViewSet for relation>, '<related field name>')
```

NOTE: Often times the `<entry in API related field>` will be the same as `<related field name>` but this is not always the case.


## Many-to-Many

If the two relations were many-to-many fields the following `related` items `team` and `organizations` for each users. For many-to-many relations you would also end up with associate/disassociate urls off the related endpoints like:
  * `/api/service/v1/users/:id/teams/associate`
  * `/api/service/v1/users/:id/teams/disassociate`
  * `/api/service/v1/users/:id/organizations/associate`
  * `/api/service/v1/users/:id/organizations/disassociate`


## Reverse Foreign Key

If the related views in our example were reverse foreign keys we would end up with the following read only related endpoints:
  * `/api/service/v1/users/:id/teams/`
  * `/api/service/v1/users/:id/organizations/`

The only way to change these fields are via a PATCH or PUT to the main user endpoint `/api/service/v1/users/` to change the value from teams or organizations.

Note: This example is not the best because an org/team wouldn't be related to a single user. But hopefully you get the idea.


## Default Related Names

If a model does not specify a related field name one will automatically be created by django in the format `<model._meta.model_name>_set`.
See: https://docs.djangoproject.com/en/dev/topics/db/queries/#backwards-related-objects

For example, in the AuthenticatorMap model we define a foreign key to authenticator like:
```
    authenticator = models.ForeignKey(
        Authenticator,
        null=False,
        on_delete=models.CASCADE,
        help_text="The authenticator this mapping belongs to",
    )
```

We do not specify the related name so Django will default the relations to `authenticatormap_set`.

If we added a related name like:
```
    authenticator = models.ForeignKey(
        Authenticator,
        null=False,
        on_delete=models.CASCADE,
        help_text="The authenticator this mapping belongs to",
        related_name='some_relation',
    )
```

Than the field we need to specify in the third parameter of the router is `some_relation`.


# Ignoring Relations

If there is any relation you don't want to be displayed in the API you can set the 'ignore_relations' field on your objects. 

Following along with the example above, if we didn't want the API to show `teams` under the `related` field on an organization than on the Organization model we would add:
```
    ignore_relations = ['teams']
```

Be sure to not include the reverse_view or related_view on the router registration or the view will still be present just not listed in the API. 


# Combining Relations

Its possible to specify multiple fields to combine into a single relation for reverse m2m views.
For example, lets say a user has two relations to the Organization model:
  * organizations (indicating membership)
  * organizations_administrated (indicating a different type of membership)

The following route would only show the `organizations` related fields:
```
router.register(
    r'users',
    views.UserViewSet,
    related_views={
        'organizations': (views.OrganizationViewSet, 'organizations'),
    },
)
```

But maybe you want your `/users/:id/organizations` endpoint to show the conglomeration of the two relationships. In this case we can turn the second argument into an array indicating to the router to conglomerate the fields:
```
router.register(
    r'users',
    views.UserViewSet,
    related_views={
        'organizations': (views.OrganizationViewSet, ['organizations', 'organizations_administrated']),
    },
)
```

Note, this should only be done for reverse relationships because these views will not have the associated/disassociate actions with them. If you perform this on a forward relationship it will show the conglomeration of fields but the associate/disassociate will only apply to the first relationship in the list. 
