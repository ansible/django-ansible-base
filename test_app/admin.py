from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group

from test_app.models import EncryptionModel, Organization, Team, User

admin.site.register(EncryptionModel)
admin.site.register(Organization)
admin.site.register(Team)
admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
