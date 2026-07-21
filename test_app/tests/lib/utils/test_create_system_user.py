from unittest.mock import patch

import pytest
from ansible_base.lib.utils.create_system_user import create_system_user, get_system_username
from ansible_base.lib.utils.models import get_system_user
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

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
        User.all_objects.filter(username=get_system_username()[0]).delete()
        create_system_user(user_model=ManagedUser)

        assert ManagedUser.objects.filter(username=get_system_username()[0]).count() == 0
        assert ManagedUser.all_objects.filter(username=get_system_username()[0]).count() == 1


class TestGetSystemUserCache:
    """Tests for the get_system_user() Redis caching behavior."""

    @pytest.mark.django_db
    def test_second_call_returns_cached_result(self, system_user):
        """Second call to get_system_user() should return from cache when a shared backend is configured."""
        with patch('ansible_base.lib.utils.models._has_shared_cache', return_value=True):
            from django.core.cache import cache

            cache.delete('dab:system_user')

            user1 = get_system_user()
            assert user1 is not None
            assert cache.get('dab:system_user') is not None

            user2 = get_system_user()
            assert user2.pk == user1.pk

    @pytest.mark.django_db
    def test_no_caching_without_shared_backend(self, system_user):
        """When no shared cache backend is available, every call queries the DB."""
        with patch('ansible_base.lib.utils.models._has_shared_cache', return_value=False):
            from django.core.cache import cache

            cache.delete('dab:system_user')

            get_system_user()
            assert cache.get('dab:system_user') is None

    @pytest.mark.django_db
    def test_cache_not_set_for_none_result(self):
        """If system user creation returns None, the result is not cached."""
        with patch('ansible_base.lib.utils.models._has_shared_cache', return_value=True):
            from django.core.cache import cache

            cache.delete('dab:system_user')

            with patch('ansible_base.lib.utils.models.create_system_user', return_value=None):
                with override_settings(SYSTEM_USERNAME='nonexistent_cache_test_user'):
                    result = get_system_user()

            assert result is None
            assert cache.get('dab:system_user') is None

    @pytest.mark.django_db
    def test_clear_system_user_cache(self, system_user):
        """clear_system_user_cache() removes the cached entry from the shared backend."""
        from ansible_base.lib.utils.models import clear_system_user_cache

        with patch('ansible_base.lib.utils.models._has_shared_cache', return_value=True):
            from django.core.cache import cache

            cache.delete('dab:system_user')

            get_system_user()
            assert cache.get('dab:system_user') is not None

            clear_system_user_cache()
            assert cache.get('dab:system_user') is None

    @pytest.mark.django_db
    def test_save_invalidates_cache(self, system_user):
        """Saving the system user should clear the cache."""
        with patch('ansible_base.lib.utils.models._has_shared_cache', return_value=True):
            from django.core.cache import cache

            cache.delete('dab:system_user')

            get_system_user()
            assert cache.get('dab:system_user') is not None

            system_user.save()
            assert cache.get('dab:system_user') is None
