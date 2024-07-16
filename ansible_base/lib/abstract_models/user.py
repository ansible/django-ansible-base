from django.contrib.auth.models import AbstractUser, UserManager


class AbstractDABUser(AbstractUser):
    class Meta(AbstractUser.Meta):
        abstract = True

    all_objects = UserManager()
    objects = UserManager()
