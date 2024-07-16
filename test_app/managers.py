from django.contrib.auth.models import UserManager


class UserUnmanagedManager(UserManager):
    def get_queryset(self):
        return super().get_queryset().filter(managed=False)
