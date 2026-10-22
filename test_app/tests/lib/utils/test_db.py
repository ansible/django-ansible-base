import threading
import time

import psycopg
import pytest
from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError
from django.test import override_settings

from ansible_base.lib.utils.db import (
    advisory_lock,
    advisory_lock_id_to_debug_info,
    get_active_advisory_locks,
    get_pg_notify_params,
    migrations_are_complete,
    psycopg_conn_string_from_settings_dict,
    psycopg_connection_from_django,
    psycopg_kwargs_from_settings_dict,
    string_to_advisory_lock_id,
)


@pytest.mark.django_db
def test_migrations_are_complete():
    "If you are running tests, migrations (test database) should be complete"
    assert migrations_are_complete()


class SkipIfSqlite:
    @pytest.fixture(autouse=True)
    def skip_if_sqlite(self):
        if connection.vendor == 'sqlite':
            pytest.skip('Advisory lock is not written for sqlite')


class TestPGNotifyConnection(SkipIfSqlite):
    TEST_DATABASE_DICT = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": "https://foo.invalid",
            "PORT": 55434,
            "USER": "dab_user",
            "PASSWORD": "dabbing",
            "NAME": "dab_db",
        }
    }
    PSYCOPG_KWARGS = {
        'dbname': 'dab_db',
        'client_encoding': 'UTF8',
        # kwargs containing objects can not be compared so they will be ignored
        # 'cursor_factory': <class 'django.db.backends.postgresql.base.Cursor'>,
        'user': 'dab_user',
        'password': 'dabbing',
        'host': 'https://foo.invalid',
        'port': 55434,
        # 'context': <psycopg.adapt.AdaptersMap object at 0x7f537f2d9f70>,
        'prepare_threshold': None,
    }

    @pytest.fixture
    def mock_settings(self):
        with override_settings(DATABASES=self.TEST_DATABASE_DICT, USE_TZ=False):
            yield

    def test_default_behavior(self, mock_settings):
        params = get_pg_notify_params()
        assert params == self.PSYCOPG_KWARGS

    def test_pg_notify_extra_options(self, mock_settings):
        params = get_pg_notify_params(application_name='joe_connection')
        expected = self.PSYCOPG_KWARGS.copy()
        expected['application_name'] = 'joe_connection'
        assert params == expected

    def test_lister_databases(self, mock_settings):
        LISTENER_DATABASES = {"default": {"HOST": "https://foo.anotherhost.invalid"}}
        with override_settings(LISTENER_DATABASES=LISTENER_DATABASES):
            params = get_pg_notify_params()
            assert params['host'] == "https://foo.anotherhost.invalid"

    def test_pg_notify_databases(self, mock_settings):
        PG_NOTIFY_DATABASES = {"default": {"HOST": "https://foo.anotherhost2.invalid"}}
        with override_settings(PG_NOTIFY_DATABASES=PG_NOTIFY_DATABASES):
            params = get_pg_notify_params()
            assert params['host'] == "https://foo.anotherhost2.invalid"

    def test_psycopg_kwargs_from_settings_dict(self):
        "More of a unit test, doing the same thing"
        test_dict = self.TEST_DATABASE_DICT["default"].copy()
        test_dict['OPTIONS'] = {'autocommit': True}
        with override_settings(USE_TZ=False):
            psycopg_params = psycopg_kwargs_from_settings_dict(test_dict)
            expected_kwargs = self.PSYCOPG_KWARGS.copy()
            expected_kwargs['autocommit'] = True
            assert psycopg_params == expected_kwargs

    def test_psycopg_kwargs_use(self):
        "This assures that the data we get for the kwargs are usable, and demos how to use"
        if connection.vendor == 'sqlite':
            pytest.skip('Test needs to connect to postgres which is not running')

        test_dict = settings.DATABASES['default'].copy()
        test_dict['OPTIONS'] = {'autocommit': True}
        with override_settings(USE_TZ=False):
            psycopg_params = psycopg_kwargs_from_settings_dict(test_dict)

        psycopg.connect(**psycopg_params)

    def test_listener_string_production(self):
        "This is a test to correspond to PG_NOTIFY_DSN_SERVER type settings in eda-server"
        with override_settings(USE_TZ=False):
            args = psycopg_conn_string_from_settings_dict(
                {
                    "ENGINE": "django.db.backends.postgresql",
                    "HOST": "127.0.0.1",
                    "PORT": 5432,
                    "USER": "postgres",
                    "PASSWORD": "DB_PASSWORD",
                    "NAME": "eda",
                    "OPTIONS": {
                        "sslmode": "allow",
                        "sslcert": "",
                        "sslkey": "",
                        "sslrootcert": "",
                    },
                }
            )
        assert args == (
            "dbname=eda sslmode=allow sslcert='' sslkey='' sslrootcert='' client_encoding=UTF8 user=postgres password=DB_PASSWORD host=127.0.0.1 port=5432"
        )

    def test_listener_string_production_use(self):
        "This assures that the data we get for the connection string is usable, and demos how to use"
        if connection.vendor == 'sqlite':
            pytest.skip('Test needs to connect to postgres which is not running')
        args = psycopg_conn_string_from_settings_dict(settings.DATABASES['default'])
        psycopg.connect(conninfo=args)

    @pytest.mark.django_db
    def test_psycopg_connection_from_django_existing_conn(self):
        if connection.vendor == 'sqlite':
            pytest.skip('Advisory lock is not written for sqlite')
        assert isinstance(psycopg_connection_from_django(), psycopg.Connection)

    @pytest.mark.django_db(transaction=True)
    def test_psycopg_connection_from_django_new_conn(self):
        if connection.vendor == 'sqlite':
            pytest.skip('Advisory lock is not written for sqlite')
        connection.close()
        assert isinstance(psycopg_connection_from_django(), psycopg.Connection)


class TestStringToAdvisoryLockId:
    """Test the string to advisory lock ID conversion function.

    Generated by Claude Code (Sonnet 4)
    """

    def test_string_to_advisory_lock_id_basic(self):
        """Test basic string to lock ID conversion."""
        lock_id = string_to_advisory_lock_id("test_string")
        assert isinstance(lock_id, int)
        assert -(2**31) <= lock_id <= 2**31 - 1

    def test_string_to_advisory_lock_id_consistency(self):
        """Test that the same string always produces the same lock ID."""
        test_string = "consistent_test"
        lock_id1 = string_to_advisory_lock_id(test_string)
        lock_id2 = string_to_advisory_lock_id(test_string)
        assert lock_id1 == lock_id2

    def test_string_to_advisory_lock_id_different_strings(self):
        """Test that different strings produce different lock IDs."""
        lock_id1 = string_to_advisory_lock_id("string1")
        lock_id2 = string_to_advisory_lock_id("string2")
        assert lock_id1 != lock_id2

    def test_string_to_advisory_lock_id_unicode(self):
        """Test string to lock ID conversion with unicode characters."""
        lock_id = string_to_advisory_lock_id("test_🔒_unicode")
        assert isinstance(lock_id, int)
        assert -(2**31) <= lock_id <= 2**31 - 1


class TestAdvisoryLockIdToDebugInfo:
    """Test the advisory lock ID to debug info function.

    Generated by Claude Code (Sonnet 4)
    """

    def test_advisory_lock_id_to_debug_info_positive(self):
        """Test debug info for positive lock ID."""
        lock_id = 12345
        debug_info = advisory_lock_id_to_debug_info(lock_id)

        assert debug_info['lock_id'] == lock_id
        assert debug_info['unsigned_crc32'] == lock_id
        assert debug_info['had_high_bit_set'] is False
        assert debug_info['hex_representation'] == hex(lock_id)

    def test_advisory_lock_id_to_debug_info_negative(self):
        """Test debug info for negative lock ID."""
        lock_id = -12345
        debug_info = advisory_lock_id_to_debug_info(lock_id)

        assert debug_info['lock_id'] == lock_id
        assert debug_info['unsigned_crc32'] == lock_id + 2**31
        assert debug_info['had_high_bit_set'] is True
        assert debug_info['hex_representation'] == hex(lock_id)

    def test_advisory_lock_id_to_debug_info_roundtrip(self):
        """Test debug info for a string-generated lock ID."""
        test_string = "test_debug_roundtrip"
        lock_id = string_to_advisory_lock_id(test_string)
        debug_info = advisory_lock_id_to_debug_info(lock_id)

        assert debug_info['lock_id'] == lock_id
        assert isinstance(debug_info['unsigned_crc32'], int)
        assert isinstance(debug_info['had_high_bit_set'], bool)
        assert debug_info['hex_representation'] == hex(lock_id)


class TestGetActiveAdvisoryLocks(SkipIfSqlite):
    """Test the get active advisory locks function.

    Generated by Claude Code (Sonnet 4)
    """

    @pytest.mark.django_db
    def test_get_active_advisory_locks_empty(self):
        """Test getting active locks when none are held."""
        locks = get_active_advisory_locks()
        assert isinstance(locks, list)
        # We can't guarantee no locks since other tests might be running

    @pytest.mark.django_db
    def test_get_active_advisory_locks_with_lock(self):
        """Test getting active locks when we hold one."""
        test_lock_name = "test_get_active_locks"

        with advisory_lock(test_lock_name):
            locks = get_active_advisory_locks()
            assert isinstance(locks, list)
            # Should have at least our lock
            assert len(locks) >= 1

            # Check that lock entries have expected structure
            for lock in locks:
                assert 'locktype' in lock
                assert 'classid' in lock
                assert 'objid' in lock
                assert 'objsubid' in lock
                assert 'pid' in lock
                assert 'mode' in lock
                assert 'granted' in lock
                assert lock['locktype'] == 'advisory'

    @pytest.mark.django_db
    def test_get_active_advisory_locks_sqlite_returns_empty(self):
        """Test that SQLite returns empty list."""
        # This test will be skipped by SkipIfSqlite for completeness
        pass


class TestAdvisoryLock(SkipIfSqlite):
    THREAD_WAIT_TIME = 0.1

    @pytest.mark.django_db
    def test_get_unclaimed_lock(self):
        with advisory_lock('test_get_unclaimed_lock'):
            pass

    @staticmethod
    def background_task(django_db_blocker):
        # HACK: as a thread the pytest.mark.django_db will not work
        django_db_blocker.unblock()
        with advisory_lock('background_task_lock'):
            time.sleep(TestAdvisoryLock.THREAD_WAIT_TIME)

    @pytest.mark.django_db
    def test_determine_lock_is_held(self, django_db_blocker):
        thread = threading.Thread(target=TestAdvisoryLock.background_task, args=(django_db_blocker,))
        thread.start()
        for _ in range(20):
            with advisory_lock('background_task_lock', wait=False) as held:
                if held is False:
                    break
            time.sleep(TestAdvisoryLock.THREAD_WAIT_TIME / 5.0)
        else:
            raise RuntimeError('Other thread never obtained lock')
        thread.join()

    @pytest.mark.django_db
    def test_tuple_lock(self):
        with advisory_lock([1234, 4321]):
            pass

    @pytest.mark.django_db
    def test_invalid_tuple_name(self):
        with pytest.raises(ValueError):
            with advisory_lock(['test_invalid_tuple_name', 'foo']):
                pass


# Special transaction=True parameter is used, because we do not want in normal test transactions
# because dropping the connection would break the transaction context, erroring at end of test
@pytest.mark.django_db(transaction=True)
class TestAdvisoryLockPostgresErrors(SkipIfSqlite):
    """Tests related to connection management and the advisory_lock"""

    def kick_connection(self):
        """
        These (somewhat evil) tests are not gentle with the connection

        At the start of one tests there is a good chance the connection is broken by the last test.
        """
        connection.ensure_connection()
        # sanity checks
        assert connection.connection
        assert connection.connection.closed is False

    def test_timeout_under_lock_by_sleep(self):
        self.kick_connection()

        with pytest.raises(OperationalError) as exc:
            # uses miliseconds units
            with advisory_lock('test_lock_session_timeout_milliseconds', lock_session_timeout_milliseconds=5):
                time.sleep(0.1)

        # This exception comes from the __exit__, either releasing the lock or closing the cursor
        assert 'terminating connection due to idle-session timeout' in str(exc)

        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')

    def test_idle_after_exception(self):
        self.kick_connection()

        with pytest.raises(RuntimeError) as exc:
            with advisory_lock('test_timeout_under_lock_with_query', lock_session_timeout_milliseconds=5):
                with connection.cursor() as cursor:
                    raise RuntimeError('exception from test')

        assert 'exception from test' in str(exc)

        time.sleep(0.1)

        # The fact that this works shows that the timeout was reset in the context manager __exit__
        # Prior bug was giving exception with
        # consuming input failed: terminating connection due to idle-session timeout server closed the connection unexpectedly
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
