import logging

from crum import get_current_user
from django.contrib.auth import get_user_model
from django.db import models
from django.urls.exceptions import NoReverseMatch
from django.utils.timezone import now
from inflection import underscore
from rest_framework.reverse import reverse

logger = logging.getLogger('ansible_base.models.common')


class CommonModel(models.Model):
    # These are fields that should be reversed lookup as related fields.
    # For example, an environment has related organizations so environment might specify reverse_foreign_key_fields = ['organizations']
    # This would end up with a view like environment/1/organizations
    reverse_foreign_key_fields = []

    class Meta:
        abstract = True

    created_on = models.DateTimeField(
        default=None,
        editable=False,
        help_text="The date/time this resource was created",
    )
    created_by = models.ForeignKey(
        get_user_model(),
        related_name='%(app_label)s_%(class)s_created+',
        default=None,
        null=True,
        editable=False,
        on_delete=models.DO_NOTHING,
        help_text="The user who created this resource",
    )
    modified_on = models.DateTimeField(
        default=None,
        editable=False,
        help_text="The date/time this resource was created",
    )
    modified_by = models.ForeignKey(
        get_user_model(),
        related_name='%(app_label)s_%(class)s_modified+',
        default=None,
        null=True,
        editable=False,
        on_delete=models.DO_NOTHING,
        help_text="The user who last modified this resource",
    )

    def save(self, *args, **kwargs):
        update_fields = list(kwargs.get('update_fields', []))
        user = get_current_user()
        # Manually perform auto_now_add and auto_now logic.
        if not self.pk and not self.created_on:
            self.created_on = now()
            self.created_by = user
            if 'created_on' not in update_fields:
                update_fields.append('created_on')
            if 'created_by' not in update_fields:
                update_fields.append('created_by')
        if 'modified_on' not in update_fields or not self.modified_on:
            self.modified_on = now()
            self.modified_by = user
            update_fields.append('modified_on')
            update_fields.append('modified_by')
        super().save(*args, **kwargs)

    def get_summary_fields(self):
        response = {}
        for field in self._meta.concrete_fields:
            if isinstance(field, models.ForeignKey) and getattr(self, field.name):
                # ignore relations on inherited django models
                if field.name.endswith("_ptr"):
                    continue
                if hasattr(getattr(self, field.name), 'summary_fields'):
                    response[field.name] = getattr(self, field.name).summary_fields()
        return response

    def related_fields(self, request):
        response = {}
        # Automatically add all of the ForeignKeys for the model as related fields
        for field in self._meta.concrete_fields:
            if isinstance(field, models.ForeignKey) and getattr(self, field.name):
                # ignore relations on inherited django models
                if field.name.endswith("_ptr"):
                    continue
                pk = getattr(self, field.name).pk
                if pk:
                    reverse_view = f"{underscore(field.related_model.__name__)}-detail"
                    try:
                        response[field.name] = reverse(reverse_view, kwargs={'pk': pk})
                    except NoReverseMatch:
                        logger.error(f"Model {self.__class__.__name__} wanted to reverse view to {reverse_view} but said view is not defined")

        # Add any reverse relations required
        for field in getattr(self, 'reverse_foreign_key_fields', []):
            reverse_view = f"{underscore(self.__class__.__name__)}-{field}"
            response[field] = reverse(reverse_view, kwargs={'pk': self.pk})

        return response

    def summary_fields(self):
        response = {}
        response['id'] = self.id
        return response


class UniqueNamedCommonModel(CommonModel):
    class Meta:
        abstract = True

    name = models.CharField(
        max_length=512,
        unique=True,
        help_text="The name of this resource",
    )

    def summary_fields(self):
        res = super().summary_fields()
        res['name'] = self.name
        return res

    def __str__(self):
        return self.name
