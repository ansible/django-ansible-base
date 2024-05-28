# Associative Resource Router

django-ansible-base provides an `AssociationResourceRouter` which will auto-construct 3 endpoints for related ManyToMany fields for your models.

1. Read-only listing of items at `/api/v2/parent_objects/:id/relationship/`
2. An `/associate` write-only endpoint with (1) as URL base
3. A `/disassociate` write-only endpoint with (1) as URL base

This can also be used for reverse relationships, which will only construct (1).

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

## Related fields

The AssociationResourceRouter works by adding a `related_views` field to the register function. For example, consider this register command:
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

The router interrogates the parent viewset (`views.UserViewSet`) along with the related viewset (ex. `views.TeamViewSet` above) and automatically constructuts a new viewset for the related teams of a user. If the relation is a many-to-many, associate and disassociate endpoints are added, and if it is a reverse foreign key it only provides list.

Related views are expressed in the following format:

```
    '<entry in API related field>': (<ViewSet for relation>, '<related field name>')
```

NOTE: Often times the `<entry in API related field>` will be the same as `<related field name>` but this is not always the case.


## Customization

Several methods defined in the `<ViewSet for relation>` will have an effect on constructed related endpoints.
Those are:

 - `get_sublist_queryset` - items shown in the listing _before_ filtering, OR candidate items for disassociation
 - `filter_queryset` - filter applied to items shown in sublist, typically RBAC filtering of what the request user can view in addition to filters from query params
 - `filter_associate_queryset` - filter to items user should be able to associate, defers to `filter_queryset` by default
 - `perform_associate` - associate items
 - `perform_disassociate` - disassociate items

These are intended to be overwritten for customization.
For heavy customizations, you can either manage this on your existing viewset like `views.TeamViewSet`
or introduce a new class that subclasses from that.

If you want a sublist to show all items, then you probably need to create a new class for the related viewset.
This is because `filter_queryset` is used for the global lists as well (like `/api/v1/teams/`), so you likely
will need a new class so that sublist-specific behavior is non-conflicting with the global list.


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
