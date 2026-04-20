from django.contrib.auth.models import AbstractUser, UserManager


class AbstractDABUser(AbstractUser):
    class Meta(AbstractUser.Meta):
        abstract = True

    # When True, the pre_save signal skips ORM-level email enforcement,
    # deferring to serializer-level protection (e.g. CommonUserSerializer).
    EMAIL_ENFORCEMENT_VIA_SERIALIZER = False

    all_objects = UserManager()
    objects = UserManager()
