from django.apps import apps
from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.mssql.bulk import MSSQLSafeManager

from .content_type import DABContentType


class DABPermissionManager(MSSQLSafeManager):
    def load_remote_objects(self, remote_data: list[dict], update_managed=False):
        """Load the permission list from a remote system, requires types are loaded first

        The remote_data should be the results from the /service-index/role-permissions/ endpoint
        of another system.
        This will save those remote permissions into the local database so we can track remote RBAC.

        update_managed being True will refresh the managed roles like Organization Admin
        so that if the algorithm includes any new permissions, those are added.
        """
        for remote_perm_raw in remote_data:
            remote_perm = remote_perm_raw.copy()
            codename = remote_perm.pop('codename')
            ct_slug = remote_perm.pop('content_type')
            ct = DABContentType.objects.get(api_slug=ct_slug)
            ct, _ = self.get_or_create(codename=codename, content_type=ct, defaults=remote_perm)

        if update_managed:
            from ansible_base.rbac import permission_registry

            permission_registry.create_managed_roles(apps, update_perms=True)


class DABPermission(models.Model):
    "This is a minimal copy of auth.Permission for internal use"

    name = models.CharField("name", max_length=255, help_text=_("The name of this permission."))
    content_type = models.ForeignKey(
        DABContentType,
        models.CASCADE,
        verbose_name="content type",
        help_text=_("The content type this permission will apply to."),
        related_name='dab_permissions',
    )
    codename = models.CharField(
        "codename",
        max_length=100,
        help_text=_(
            "".join(
                [
                    "A codename for the permission, in the format {action}_{model_name}. ",
                    "Where action is typically the view set action (view/list/etc) from Django rest framework.",
                ]
            )
        ),
    )
    api_slug = models.CharField(
        max_length=201,  # combines content_type.service and codename fields with a period in-between
        default='',
        help_text=_("String to use for references to this type from other models in the API."),
    )

    objects = DABPermissionManager()

    class Meta:
        app_label = 'dab_rbac'
        verbose_name = "permission"
        verbose_name_plural = "permissions"
        unique_together = [["content_type", "codename"]]
        ordering = ["content_type__model", "codename"]

    def __str__(self):
        return f"<{self.__class__.__name__}: {self.codename}>"

    def save(self, *args, **kwargs):
        # Set the api_slug field if it is not synchronized to other fields
        api_slug = f'{self.content_type.service}.{self.codename}'
        if api_slug != self.api_slug:
            self.api_slug = api_slug
            if update_fields := kwargs.get('update_fields', []):
                update_fields.append('api_slug')
        return super().save(*args, **kwargs)
