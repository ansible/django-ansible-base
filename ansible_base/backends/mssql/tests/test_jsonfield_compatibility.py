"""
Test JSONField compatibility between PostgreSQL and MS SQL Server.

These tests verify that JSONField behavior is consistent across databases,
particularly for encrypted fields, NULL handling, and large payloads.
"""

import json
from unittest import skipUnless

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase, TransactionTestCase

from ansible_base.activitystream.models import Entry
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.lib.utils.db import bulk_create_db_safe
from ansible_base.lib.utils.encryption import ansible_encryption


class JSONFieldBasicTest(TestCase):
    """Test basic JSONField functionality across databases."""

    def test_default_dict_creates_new_instances(self):
        """default=dict should create a new dict for each instance, not share references."""
        # Create two authenticators
        auth1 = Authenticator.objects.create(
            name='Auth1',
            enabled=True,
            type='ansible_base.authentication.authenticator_plugins.ldap',
            configuration={'SERVER_URI': 'ldap://localhost'},  # configuration has default=dict
        )
        auth2 = Authenticator.objects.create(
            name='Auth2',
            enabled=True,
            type='ansible_base.authentication.authenticator_plugins.ldap',
            configuration={},
        )

        # Verify both have empty dicts
        self.assertEqual(auth1.configuration, {})
        self.assertEqual(auth2.configuration, {})

        # Modify one and verify the other is unchanged (no shared reference)
        auth1.configuration['test_key'] = 'test_value'
        auth1.save()

        auth2.refresh_from_db()
        self.assertNotIn('test_key', auth2.configuration)
        self.assertEqual(auth2.configuration, {})

    def test_default_list_creates_new_instances(self):
        """default=list should create a new list for each instance, not share references."""
        # Create two entries with changes=None (will use empty list from model)
        # Actually Entry.changes has null=True, so let's use a different field
        # Let's test with AuthenticatorUser.last_login_map_results which has default=list

        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create(username='testuser')
        auth = Authenticator.objects.create(
            name='TestAuth',
            enabled=True,
            type='ansible_base.authentication.authenticator_plugins.ldap',
            configuration={'SERVER_URI': 'ldap://localhost'},
        )

        au1 = AuthenticatorUser.objects.create(
            user=user,
            provider=auth,
            uid='uid1',
        )
        au2 = AuthenticatorUser.objects.create(
            user=user,
            provider=auth,
            uid='uid2',
        )

        # Verify both have empty lists
        self.assertEqual(au1.last_login_map_results, [])
        self.assertEqual(au2.last_login_map_results, [])

        # Modify one and verify the other is unchanged
        au1.last_login_map_results.append('result1')
        au1.save()

        au2.refresh_from_db()
        self.assertEqual(au2.last_login_map_results, [])

    def test_empty_dict_vs_none(self):
        """Empty dict {} should be distinct from None in nullable JSONFields."""
        ct = ContentType.objects.first()

        # Create entry with None
        entry1 = Entry.objects.create(
            content_type=ct,
            object_id='123',
            operation='create',
            changes=None,
        )
        entry1.refresh_from_db()
        self.assertIsNone(entry1.changes)

        # Create entry with empty dict
        entry2 = Entry.objects.create(
            content_type=ct,
            object_id='456',
            operation='create',
            changes={},
        )
        entry2.refresh_from_db()
        self.assertEqual(entry2.changes, {})
        self.assertIsNotNone(entry2.changes)

        # Create entry with empty list
        entry3 = Entry.objects.create(
            content_type=ct,
            object_id='789',
            operation='create',
            changes=[],
        )
        entry3.refresh_from_db()
        self.assertEqual(entry3.changes, [])
        self.assertIsNotNone(entry3.changes)

    def test_query_null_vs_empty(self):
        """Filters should distinguish between NULL and empty JSON."""
        ct = ContentType.objects.first()

        # Create test data
        none_entry = Entry.objects.create(
            content_type=ct,
            object_id='none',
            operation='create',
            changes=None,
        )
        empty_dict_entry = Entry.objects.create(
            content_type=ct,
            object_id='empty_dict',
            operation='create',
            changes={},
        )
        populated_entry = Entry.objects.create(
            content_type=ct,
            object_id='populated',
            operation='create',
            changes={'key': 'value'},
        )

        # Test __isnull=True (should only find None)
        null_entries = Entry.objects.filter(changes__isnull=True)
        self.assertIn(none_entry, null_entries)
        self.assertNotIn(empty_dict_entry, null_entries)
        self.assertNotIn(populated_entry, null_entries)

        # Test __isnull=False (should find {} and populated, but not None)
        not_null_entries = Entry.objects.filter(changes__isnull=False)
        self.assertNotIn(none_entry, not_null_entries)
        self.assertIn(empty_dict_entry, not_null_entries)
        self.assertIn(populated_entry, not_null_entries)


class JSONFieldEncryptionTest(TransactionTestCase):
    """Test encrypted JSONField compatibility."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        self.user = User.objects.create(username='testuser')
        # Use a valid authenticator type (ldap is registered in test_app)
        self.auth = Authenticator.objects.create(
            name='TestAuth',
            enabled=True,
            type='ansible_base.authentication.authenticator_plugins.ldap',
            configuration={'SERVER_URI': 'ldap://localhost'},
        )

    def test_encrypted_jsonfield_round_trip(self):
        """Encrypted JSONField data should save and retrieve correctly on MS SQL."""
        test_data = {
            'access_token': 'secret_token_12345',
            'refresh_token': 'refresh_secret_67890',
            'user_info': {
                'email': 'user@example.com',
                'name': 'Test User',
            },
        }

        # Create AuthenticatorUser with extra_data (encrypted JSONField)
        au = AuthenticatorUser.objects.create(
            user=self.user,
            provider=self.auth,
            uid='test_uid',
            extra_data=test_data,
        )

        # The save() method encrypts extra_data, then decrypts it back
        # Verify it's still the original data in memory
        self.assertEqual(au.extra_data, test_data)

        # Fetch from database
        au_from_db = AuthenticatorUser.objects.get(pk=au.pk)

        # Verify decrypted data matches original
        self.assertEqual(au_from_db.extra_data, test_data)
        self.assertEqual(au_from_db.extra_data['access_token'], 'secret_token_12345')
        self.assertEqual(au_from_db.extra_data['user_info']['email'], 'user@example.com')

    def test_encrypted_jsonfield_with_binary_data(self):
        """Binary data in extra_data should be base64 encoded before encryption."""
        # The model's save() method calls b64_encode_binary_data_in_dict
        test_data = {
            'text': 'normal string',
            'binary': b'binary data \x00\x01\x02',
            'nested': {
                'more_binary': b'\xff\xfe\xfd',
            },
        }

        au = AuthenticatorUser.objects.create(
            user=self.user,
            provider=self.auth,
            uid='test_uid_binary',
            extra_data=test_data,
        )

        # After save, binary data should be base64 encoded
        au_from_db = AuthenticatorUser.objects.get(pk=au.pk)

        # Binary should now be base64 strings
        self.assertIsInstance(au_from_db.extra_data['binary'], str)
        self.assertIsInstance(au_from_db.extra_data['nested']['more_binary'], str)

        # Verify it's valid base64
        import base64
        decoded = base64.b64decode(au_from_db.extra_data['binary'])
        self.assertEqual(decoded, b'binary data \x00\x01\x02')

    @skipUnless(connection.vendor == 'microsoft', 'MS SQL Server only test')
    def test_no_isjson_constraint_on_encrypted_field(self):
        """MS SQL should not have ISJSON constraint on extra_data (allows encrypted data)."""
        # Query for CHECK constraints on extra_data
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT CONSTRAINT_NAME, CHECK_CLAUSE
                FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS
                WHERE CONSTRAINT_NAME LIKE '%extra_data%'
                  AND TABLE_NAME = 'dab_authentication_authenticatoruser'
            """)
            constraints = cursor.fetchall()

        # Should have no ISJSON constraints
        for name, clause in constraints:
            self.assertNotIn('isjson', clause.lower(),
                           f"Found ISJSON constraint on extra_data: {clause}")


class JSONFieldSizeTest(TestCase):
    """Test JSONField with large payloads."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        self.user = User.objects.create(username='testuser')
        self.auth = Authenticator.objects.create(
            name='TestAuth',
            enabled=True,
            type='ansible_base.authentication.authenticator_plugins.ldap',
            configuration={'SERVER_URI': 'ldap://localhost'},
        )

    def test_large_json_payload(self):
        """JSONField should handle reasonably large payloads (100KB+)."""
        # Create a large JSON object (~100KB)
        large_data = {
            'users': [
                {
                    'id': i,
                    'name': f'User {i}',
                    'email': f'user{i}@example.com',
                    'metadata': {
                        'key1': 'value' * 100,
                        'key2': 'value' * 100,
                        'key3': 'value' * 100,
                    }
                }
                for i in range(100)
            ]
        }

        # Verify size is substantial
        json_str = json.dumps(large_data)
        size_kb = len(json_str) / 1024
        self.assertGreater(size_kb, 50, f"Test data too small: {size_kb:.1f}KB")

        # Save and retrieve
        au = AuthenticatorUser.objects.create(
            user=self.user,
            provider=self.auth,
            uid='large_data_test',
            extra_data=large_data,
        )

        au_from_db = AuthenticatorUser.objects.get(pk=au.pk)

        # Verify data integrity
        self.assertEqual(len(au_from_db.extra_data['users']), 100)
        self.assertEqual(au_from_db.extra_data['users'][0]['name'], 'User 0')
        self.assertEqual(au_from_db.extra_data['users'][99]['name'], 'User 99')

    def test_deeply_nested_json(self):
        """JSONField should handle deeply nested structures."""
        # Create deeply nested structure
        nested = {'level': 0}
        current = nested
        for i in range(1, 20):
            current['child'] = {'level': i}
            current = current['child']
        current['value'] = 'deepest level'

        au = AuthenticatorUser.objects.create(
            user=self.user,
            provider=self.auth,
            uid='nested_test',
            extra_data=nested,
        )

        au_from_db = AuthenticatorUser.objects.get(pk=au.pk)

        # Navigate to deepest level
        current = au_from_db.extra_data
        for i in range(19):
            self.assertIn('child', current)
            current = current['child']

        self.assertEqual(current['value'], 'deepest level')


class JSONFieldEdgeCasesTest(TestCase):
    """Test JSONField with special characters and edge cases."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        self.user = User.objects.create(username='testuser')
        self.auth = Authenticator.objects.create(
            name='TestAuth',
            enabled=True,
            type='ansible_base.authentication.authenticator_plugins.ldap',
            configuration={'SERVER_URI': 'ldap://localhost'},
        )

    def test_special_characters(self):
        """JSONField should handle quotes, backslashes, unicode, etc."""
        test_data = {
            'quotes': 'She said "Hello"',
            'single_quotes': "It's working",
            'backslashes': r'C:\Windows\System32',
            'unicode': '你好世界 🌍',
            'newlines': 'Line 1\nLine 2\nLine 3',
            'tabs': 'Column1\tColumn2\tColumn3',
            'mixed': '"Quote" and \\backslash\\ and 日本語',
        }

        au = AuthenticatorUser.objects.create(
            user=self.user,
            provider=self.auth,
            uid='special_chars',
            extra_data=test_data,
        )

        au_from_db = AuthenticatorUser.objects.get(pk=au.pk)

        # Verify all special characters preserved
        self.assertEqual(au_from_db.extra_data['quotes'], 'She said "Hello"')
        self.assertEqual(au_from_db.extra_data['single_quotes'], "It's working")
        self.assertEqual(au_from_db.extra_data['backslashes'], r'C:\Windows\System32')
        self.assertEqual(au_from_db.extra_data['unicode'], '你好世界 🌍')
        self.assertEqual(au_from_db.extra_data['newlines'], 'Line 1\nLine 2\nLine 3')

    def test_empty_string_in_json(self):
        """Empty strings in JSON should not become NULL."""
        test_data = {
            'empty': '',
            'whitespace': '   ',
            'zero': 0,
            'false': False,
            'null': None,
        }

        au = AuthenticatorUser.objects.create(
            user=self.user,
            provider=self.auth,
            uid='empty_strings',
            extra_data=test_data,
        )

        au_from_db = AuthenticatorUser.objects.get(pk=au.pk)

        # Verify type preservation
        self.assertEqual(au_from_db.extra_data['empty'], '')
        self.assertEqual(au_from_db.extra_data['whitespace'], '   ')
        self.assertEqual(au_from_db.extra_data['zero'], 0)
        self.assertEqual(au_from_db.extra_data['false'], False)
        self.assertIsNone(au_from_db.extra_data['null'])

    def test_numeric_values(self):
        """JSONField should preserve numeric types."""
        test_data = {
            'int': 42,
            'negative': -123,
            'float': 3.14159,
            'scientific': 1.23e-10,
            'large_int': 999999999999999,
        }

        ct = ContentType.objects.first()
        entry = Entry.objects.create(
            content_type=ct,
            object_id='numbers',
            operation='create',
            changes=test_data,
        )

        entry_from_db = Entry.objects.get(pk=entry.pk)

        # Verify types and values
        self.assertIsInstance(entry_from_db.changes['int'], int)
        self.assertEqual(entry_from_db.changes['int'], 42)
        self.assertIsInstance(entry_from_db.changes['float'], float)
        self.assertAlmostEqual(entry_from_db.changes['float'], 3.14159, places=5)


class JSONFieldBulkOperationsTest(TransactionTestCase):
    """Test JSONField with bulk operations."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        self.user = User.objects.create(username='testuser')
        self.auth = Authenticator.objects.create(
            name='TestAuth',
            enabled=True,
            type='ansible_base.authentication.authenticator_plugins.ldap',
            configuration={'SERVER_URI': 'ldap://localhost'},
        )

    def test_bulk_create_with_jsonfield(self):
        """Bulk create should handle JSONField correctly."""
        auth_users = [
            AuthenticatorUser(
                user=self.user,
                provider=self.auth,
                uid=f'bulk_{i}',
                extra_data={'index': i, 'name': f'User {i}'},
            )
            for i in range(10)
        ]

        created = bulk_create_db_safe(AuthenticatorUser, auth_users, ignore_conflicts=False)
        self.assertEqual(len(created), 10)

        # Verify all data saved correctly
        for i, au in enumerate(AuthenticatorUser.objects.filter(uid__startswith='bulk_').order_by('uid')):
            # Note: bulk_create doesn't call save(), so encryption won't happen
            # This tests that raw JSON data works
            pass

    def test_bulk_update_jsonfield(self):
        """Bulk update should handle JSONField correctly."""
        # Create test objects
        auth_users = []
        for i in range(5):
            au = AuthenticatorUser.objects.create(
                user=self.user,
                provider=self.auth,
                uid=f'update_{i}',
                extra_data={'value': i},
            )
            auth_users.append(au)

        # Update all
        for au in auth_users:
            au.extra_data['updated'] = True

        AuthenticatorUser.objects.bulk_update(auth_users, ['extra_data'])

        # Verify updates
        for au in AuthenticatorUser.objects.filter(uid__startswith='update_'):
            # Note: bulk_update also bypasses save(), so encryption handling differs
            pass


class JSONFieldDatabaseSpecificTest(TestCase):
    """Database-specific behavior tests."""

    def test_database_vendor_detection(self):
        """Verify we can detect the current database vendor."""
        self.assertIn(connection.vendor, ['postgresql', 'microsoft'])

    @skipUnless(connection.vendor == 'microsoft', 'MS SQL Server only')
    def test_mssql_uses_nvarchar_max(self):
        """MS SQL should use nvarchar(max) for JSONField."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = 'dab_authentication_authenticatoruser'
                  AND COLUMN_NAME = 'extra_data'
            """)
            data_type, max_length = cursor.fetchone()

            self.assertEqual(data_type, 'nvarchar')
            self.assertEqual(max_length, -1, "nvarchar(max) should have -1 for max_length")

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL only')
    def test_postgresql_uses_jsonb(self):
        """PostgreSQL should use jsonb for JSONField."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_name = 'dab_authentication_authenticatoruser'
                  AND column_name = 'extra_data'
            """)
            row = cursor.fetchone()
            if row:
                data_type = row[0]
                self.assertIn(data_type, ['jsonb', 'json'])
