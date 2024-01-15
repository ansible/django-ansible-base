from django.contrib import admin

from test_app.models import EncryptionModel, Organization, Team

admin.site.register(EncryptionModel)
admin.site.register(Organization)
admin.site.register(Team)
