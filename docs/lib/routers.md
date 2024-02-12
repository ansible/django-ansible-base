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

# Many-to-Many fields.

The AssociationResourceRouter can also handle many to many fields by adding a `related_views` field to the register function. For example, consider this register command:
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

This would create an endpoint called users with `related` objects teams and organizations. You would also end up with associate/disassociate urls off the related endpoints like:
  * `/api/service/v1/users/:id/teams/associate`
  * `/api/service/v1/users/:id/teams/disassociate`
  * `/api/service/v1/users/:id/organizations/associate`
  * `/api/service/v1/users/:id/organizations/disassociate`


Related views are expressed in the following format:

```
    '<entry in API related field>': (<ViewSet for relation>, '<related field name>')
```

NOTE: Often times the `<entry in API related field>` will be the same as `<related field name>` but this is not always the case.


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

# One-to-Many, reverse ForeignKey

Sublists for reverse ForeignKey fields are like `/api/v1/organizations/1/teams/` where a PATCH or PUT to `/api/v1/teams/4/` could change the `organization` field on the team directly.
These sublists should be read-only, because PATCH/PUT to the related model is the preferred way of changing the link.

You can add a reverse ForeignKey filed during the register process like:
```
associative_router.register(
    r'organizations',
    views.OrganizationViewSet,
    reverse_views={
        'teams': (views.TeamViewSet, 'teams'),
    },
    basename='organization',
)
```

Reverse views are expressed in the following format:

```
    '<entry in API related field>': (<ViewSet for relation>, '<related field name>')
```

NOTE: Often times the `<entry in API related field>` will be the same as `<related field name>` but this is not always the case.

Note, that the Team model would have the ForeignKey field to the organization model but we specify on the team relation on the registration of the organization.


# Ignoring Relations

If there is any relation you don't want to be displayed in the API you can set the 'ignore_relations' field on your objects. 

Following along with the example above, if we didn't want the API to show `teams` under the `related` field on an organization than on the Organization model we would add:
```
    ignore_relations = ['teams']
```

Be sure to not include the reverse_view or related_view on the router registration or the view will still be present just not listed in the API. 
