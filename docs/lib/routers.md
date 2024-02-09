# Associative Resource Router

django-ansible-base provides an `AssociationResourceRouter` which will auto-construct /associate and /disassociate endpoints for related ManyToMany fields for your models.

To use this router simply do the following:
```
from ansible_base.lib.routers import AssociationResourceRouter

router = AssociationResourceRouter()

router.register(
    r'users',
    views.UserViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'teams'),
        'organizations': (views.OrganizationViewSet, 'organizations'),
    },
)

urlpatterns = [
    path('api/service/v1/', include(router.urls)),
]
```

This would create an endpoint called users with `related` objects teams and organizations. You would also end up with associate/disassociate urls off the related endpoints like:
  * `/api/service/v1/users/:id/teams/associate`
  * `/api/service/v1/users/:id/teams/disassociate`
  * `/api/service/v1/users/:id/organizations/associate`
  * `/api/service/v1/users/:id/organizations/disassociate`


## Breaking down related views

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
