from django.contrib import admin

from ansible_base.activitystream.models import Entry

admin.site.register(Entry)
