from django.contrib import admin


class ReadOnlyAdmin(admin.ModelAdmin):
    """
    A ModelAdmin that provides read-only access to the model.
    """

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
