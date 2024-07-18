import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from ansible_base.lib.utils.create_system_user import create_system_user, get_system_username
from test_app.models import ManagedUser, User


class TestCreateSystemUser:
    @pytest.mark.parametrize(
        "system_username_value",
        [
            None,
            'Jimmy',
            '_system',
        ],
    )
    def test_get_system_username_valid_values(self, system_username_value):
        with override_settings(SYSTEM_USERNAME=system_username_value):
            username, setting_name = get_system_username()
            assert system_username_value == username
            assert 'SYSTEM_USERNAME' == setting_name

    @pytest.mark.parametrize(
        "system_username_value",
        [
            1,
            {},
            [],
        ],
    )
    def test_get_system_username_invalid_value(self, system_username_value):
        with override_settings(SYSTEM_USERNAME=system_username_value):
            with pytest.raises(ImproperlyConfigured):
                get_system_username()

    def test_create_system_user_user_already_created(self, system_user, expected_log):
        with expected_log('ansible_base.lib.utils.create_system_user.logger', 'debug', 'System user is already created'):
            assert create_system_user(user_model=User) == system_user

    @pytest.mark.django_db
    def test_create_system_user_happy_path(self, expected_log):
        with override_settings(SYSTEM_USERNAME='_not_system'):
            with expected_log('ansible_base.lib.utils.create_system_user.logger', 'info', 'Created system user'):
                system_user = create_system_user(user_model=User)
            assert system_user.username == settings.SYSTEM_USERNAME

    @pytest.mark.django_db
    def test_create_system_user_with_managed(self, expected_log):
        with override_settings(SYSTEM_USERNAME='toad_the_wet_sprocket'):
            with expected_log('ansible_base.lib.utils.create_system_user.logger', 'info', 'Created system user'):
                system_user = create_system_user(user_model=ManagedUser)
            assert system_user.username == settings.SYSTEM_USERNAME
            assert system_user.managed is True

    @pytest.mark.django_db
    def test_create_system_user_more_than_once(self):
        create_system_user(user_model=User)
        create_system_user(user_model=User)
        create_system_user(user_model=User)

        assert User.objects.filter(username=get_system_username()[0]).count() == 1


class TestGetSystemUser:
    @pytest.mark.django_db
    def test_get_system_user_from_basic_model(self):
        create_system_user(user_model=User)

        assert User.objects.filter(username=get_system_username()[0]).count() == 1
        assert User.all_objects.filter(username=get_system_username()[0]).count() == 1

    @pytest.mark.django_db
    def test_get_system_user_from_managed_model(self):
        create_system_user(user_model=ManagedUser)

        assert ManagedUser.objects.filter(username=get_system_username()[0]).count() == 0
        assert ManagedUser.all_objects.filter(username=get_system_username()[0]).count() == 1
