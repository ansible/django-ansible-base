from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group

from test_app import models

admin.site.register(models.EncryptionModel)
admin.site.register(models.Organization)
admin.site.register(models.Team)
admin.site.register(models.User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(models.RelatedFieldsTestModel)
