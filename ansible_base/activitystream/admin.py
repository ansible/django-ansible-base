from django.contrib import admin

from ansible_base.activitystream.models import Entry
from ansible_base.lib.admin import ReadOnlyAdmin

admin.site.register(Entry, ReadOnlyAdmin)
