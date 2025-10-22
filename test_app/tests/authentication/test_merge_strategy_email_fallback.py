import pytest
from django.contrib.auth import get_user_model
from social_core.exceptions import AuthException

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.utils.authentication import determine_username_from_uid

User = get_user_model()


@pytest.fixture
def existing_user():
    """Create an existing user with an email."""
    return User.objects.create(username='john', email='john@example.com', first_name='John', last_name='Doe')


@pytest.fixture
def existing_user_with_github_auth(existing_user, github_authenticator):
    """Create an existing user linked to GitHub authenticator."""
    AuthenticatorUser.objects.create(user=existing_user, uid='john', provider=github_authenticator, extra_data={'github_id': 12345})
    return existing_user


@pytest.mark.django_db
class TestEmailFallbackMergeStrategy:
    """Test the Email fallback merge strategy logic."""

    def test_email_fallback_merge_same_email_different_authenticators(self, existing_user_with_github_auth, ldap_authenticator):
        """Test that users with same email are merged regardless of authenticator."""
        # User already exists with GitHub auth and email john@example.com
        # Now try to authenticate with LDAP using different uid but same email

        username = determine_username_from_uid(uid='john_ldap', email='john@example.com', authenticator=ldap_authenticator)

        # Should return the existing user's username (merge accounts)
        assert username == 'john'

    def test_email_fallback_merge_email_as_list(self, existing_user_with_github_auth, saml_authenticator):
        """Test that email as list is handled correctly."""
        # Email provided as list (common in SAML)
        username = determine_username_from_uid(uid='john_saml', email=['john@example.com', 'john.doe@example.com'], authenticator=saml_authenticator)

        # Should use first email and merge with existing user
        assert username == 'john'

    def test_email_fallback_no_existing_user_with_email(self, ldap_authenticator):
        """Test creating new user when no existing user has the email."""
        username = determine_username_from_uid(uid='newuser', email='newuser@example.com', authenticator=ldap_authenticator)

        # Should create a unique username since no existing user has this email
        # and no other authenticator is using this uid
        assert username == 'newuser'

    def test_email_fallback_multiple_users_same_email_raises_exception(self, ldap_authenticator):
        """Test that multiple users with same email raises an exception."""
        # Create two users with same email
        User.objects.create(username='user1', email='duplicate@example.com')
        User.objects.create(username='user2', email='duplicate@example.com')

        with pytest.raises(AuthException) as exc_info:
            determine_username_from_uid(uid='conflicting_user', email='duplicate@example.com', authenticator=ldap_authenticator)
            assert "Found more than 1 user matching" in str(exc_info.value)

    def test_email_fallback_no_email_provided_username_available(self, ldap_authenticator):
        """Test behavior when no email is provided and username is available."""
        username = determine_username_from_uid(uid='available_username', email=None, authenticator=ldap_authenticator)

        # Should use the uid as username since no conflicts
        assert username == 'available_username'

    def test_email_fallback_no_email_provided_username_taken(self, existing_user_with_github_auth, ldap_authenticator):
        """Test behavior when no email is provided and username is taken by another authenticator."""
        # Try to use 'john' which is already taken by GitHub authenticator
        username = determine_username_from_uid(uid='john', email=None, authenticator=ldap_authenticator)

        # Should create a unique username since 'john' is already used
        assert username != 'john'
        assert 'john' in username  # Should be based on original username

    def test_email_fallback_no_email_provided_username_taken_by_same_authenticator(self, existing_user_with_github_auth, github_authenticator):
        """Test behavior when user already exists for same authenticator."""
        # User 'john' already exists with GitHub authenticator
        username = determine_username_from_uid(uid='john', email=None, authenticator=github_authenticator)

        # Should return the existing username since it's the same authenticator
        assert username == 'john'

    def test_email_fallback_empty_email_string(self, ldap_authenticator):
        """Test behavior with empty email string."""
        username = determine_username_from_uid(uid='testuser', email='', authenticator=ldap_authenticator)

        # Empty email should be treated same as None
        assert username == 'testuser'

    def test_email_fallback_empty_email_list(self, ldap_authenticator):
        """Test behavior with empty email list."""
        username = determine_username_from_uid(uid='testuser', email=[], authenticator=ldap_authenticator)

        # Empty email list should be treated same as None
        assert username == 'testuser'

    def test_email_fallback_cross_authenticator_merge(self, github_authenticator, ldap_authenticator, saml_authenticator):
        """Test merging users across multiple different authenticators."""
        # Create user via GitHub
        github_user = User.objects.create(username='multiauth_user', email='multi@example.com')
        AuthenticatorUser.objects.create(user=github_user, uid='github_user', provider=github_authenticator, extra_data={'github_id': 12345})

        # Try to authenticate same email via LDAP
        ldap_username = determine_username_from_uid(uid='ldap_user', email='multi@example.com', authenticator=ldap_authenticator)

        # Should merge with existing user
        assert ldap_username == 'multiauth_user'

        # Try to authenticate same email via SAML
        saml_username = determine_username_from_uid(uid='saml_user', email='multi@example.com', authenticator=saml_authenticator)

        # Should also merge with existing user
        assert saml_username == 'multiauth_user'

    def test_email_fallback_case_insensitive_email_merge(self, existing_user_with_github_auth, ldap_authenticator):
        """Test that email comparison is case insensitive."""
        # existing_user_with_github_auth has email 'john@example.com'

        username = determine_username_from_uid(uid='john_ldap', email='JOHN@EXAMPLE.COM', authenticator=ldap_authenticator)  # Different case

        # Should still merge with existing user (case insensitive)
        assert username == 'john'

    def test_email_fallback_merge_preserves_original_username(self, github_authenticator, ldap_authenticator):
        """Test that merging preserves the original user's username."""
        # Create user with specific username and email
        original_user = User.objects.create(username='original_name', email='merge@example.com')
        AuthenticatorUser.objects.create(user=original_user, uid='github_original', provider=github_authenticator, extra_data={})

        # Try to authenticate with different uid but same email
        username = determine_username_from_uid(uid='completely_different_name', email='merge@example.com', authenticator=ldap_authenticator)

        # Should return the original username, not the new uid
        assert username == 'original_name'

    def test_email_fallback_with_whitespace_email(self, existing_user_with_github_auth, ldap_authenticator):
        """Test that email with whitespace is handled correctly."""
        # Note: This test depends on how Django handles email normalization
        username = determine_username_from_uid(uid='john_ldap', email='  john@example.com  ', authenticator=ldap_authenticator)  # Email with whitespace

        # Should still find and merge with existing user
        # (This may need adjustment based on actual email handling)
        assert username == 'john'

    def test_email_fallback_uid_conflicts_with_existing_username(self, ldap_authenticator):
        """Test when uid conflicts with existing username but different email."""
        # Create user with username 'conflict' and different email
        User.objects.create(username='conflict', email='other@example.com')

        username = determine_username_from_uid(uid='conflict', email='new@example.com', authenticator=ldap_authenticator)

        # Should create unique username since emails don't match
        assert username != 'conflict'
        assert 'conflict' in username  # Should be based on original uid

    def test_email_fallback_complex_scenario(self, github_authenticator, ldap_authenticator, saml_authenticator):
        """Test a complex scenario with multiple authenticators and email merging."""
        # Create initial user via GitHub
        github_user = User.objects.create(username='complex_user', email='complex@example.com')
        AuthenticatorUser.objects.create(user=github_user, uid='github_complex', provider=github_authenticator, extra_data={'github_id': 12345})

        # Create another user with different email
        other_user = User.objects.create(username='other_user', email='other@example.com')
        AuthenticatorUser.objects.create(user=other_user, uid='ldap_other', provider=ldap_authenticator, extra_data={})

        # Try to authenticate with SAML using same email as first user
        saml_username = determine_username_from_uid(uid='saml_complex', email='complex@example.com', authenticator=saml_authenticator)

        # Should merge with first user
        assert saml_username == 'complex_user'

        # Try to authenticate with LDAP using different uid but same email as first user
        ldap_username = determine_username_from_uid(uid='ldap_complex', email='complex@example.com', authenticator=ldap_authenticator)

        # Should also merge with first user
        assert ldap_username == 'complex_user'


@pytest.mark.django_db
class TestUidFilterParameter:
    """Test the uid_filter parameter functionality in determine_username_from_uid."""

    def test_uid_filter_single_matching_uid(self, existing_user_with_github_auth, github_authenticator):
        """Test uid_filter with single UID that matches existing AuthenticatorUser."""
        # existing_user_with_github_auth has uid 'john' with GitHub authenticator

        username = determine_username_from_uid(uid='different_uid', uid_filter=['john'], email='test@example.com', authenticator=github_authenticator)

        # Should match existing user even though uid parameter is different
        assert username == 'john'

    def test_uid_filter_multiple_uids_one_matches(self, existing_user_with_github_auth, github_authenticator):
        """Test uid_filter with multiple UIDs where one matches existing AuthenticatorUser."""
        # existing_user_with_github_auth has uid 'john' with GitHub authenticator

        username = determine_username_from_uid(
            uid='different_uid', uid_filter=['nonexistent1', 'john', 'nonexistent2'], email='test@example.com', authenticator=github_authenticator
        )

        # Should match existing user with uid 'john'
        assert username == 'john'

    def test_uid_filter_multiple_uids_multiple_matches(self, github_authenticator):
        """Test uid_filter with multiple UIDs that all match existing AuthenticatorUsers."""
        # Create two users with different UIDs for same authenticator
        user1 = User.objects.create(username='user1', email='user1@example.com')
        user2 = User.objects.create(username='user2', email='user2@example.com')

        AuthenticatorUser.objects.create(user=user1, uid='uid1', provider=github_authenticator, extra_data={})
        AuthenticatorUser.objects.create(user=user2, uid='uid2', provider=github_authenticator, extra_data={})

        username = determine_username_from_uid(uid='different_uid', uid_filter=['uid1', 'uid2'], email='test@example.com', authenticator=github_authenticator)

        # Should return the first match found
        assert username in ['user1', 'user2']

    def test_uid_filter_no_matches(self, github_authenticator):
        """Test uid_filter with UIDs that don't match any existing AuthenticatorUser."""
        username = determine_username_from_uid(
            uid='new_user', uid_filter=['nonexistent1', 'nonexistent2'], email='newuser@example.com', authenticator=github_authenticator
        )

        # Should fall back to email fallback strategy since no exact matches
        assert username == 'new_user'

    def test_uid_filter_empty_list(self, github_authenticator):
        """Test uid_filter as empty list."""
        username = determine_username_from_uid(uid='new_user', uid_filter=[], email='newuser@example.com', authenticator=github_authenticator)

        # Should fall back to default behavior (check uid parameter directly)
        assert username == 'new_user'

    def test_uid_filter_none_uses_default_behavior(self, existing_user_with_github_auth, github_authenticator):
        """Test uid_filter as None uses default behavior."""
        # existing_user_with_github_auth has uid 'john' with GitHub authenticator

        username = determine_username_from_uid(uid='john', uid_filter=None, email='test@example.com', authenticator=github_authenticator)

        # Should match existing user using uid parameter
        assert username == 'john'

    def test_uid_filter_vs_uid_parameter_difference(self, existing_user_with_github_auth, github_authenticator):
        """Test when uid parameter differs from UIDs in uid_filter."""
        # existing_user_with_github_auth has uid 'john' with GitHub authenticator

        # Case 1: uid_filter matches, uid parameter doesn't
        username = determine_username_from_uid(uid='different_uid', uid_filter=['john'], email='test@example.com', authenticator=github_authenticator)
        assert username == 'john'  # Should use uid_filter match

        # Case 2: uid parameter matches, uid_filter doesn't
        username = determine_username_from_uid(uid='john', uid_filter=['nonexistent'], email='test@example.com', authenticator=github_authenticator)
        # Should fall back to email strategy since uid_filter didn't match
        # Uses dupe user strategy and suffixes with <hash>
        assert username.startswith('john')

    def test_uid_filter_with_different_authenticator(self, existing_user_with_github_auth, ldap_authenticator):
        """Test uid_filter matching UID from different authenticator."""
        # existing_user_with_github_auth has uid 'john' with GitHub authenticator

        username = determine_username_from_uid(
            uid='different_uid',
            uid_filter=['john'],  # This UID exists but for GitHub, not LDAP
            email='john@example.com',
            authenticator=ldap_authenticator,  # Different authenticator
        )

        # Should not match because authenticator is different, but should merge via email
        assert username == 'john'

    def test_uid_filter_cross_authenticator_no_email_merge(self, existing_user_with_github_auth, ldap_authenticator):
        """Test uid_filter with different authenticator and no email merge."""
        # existing_user_with_github_auth has uid 'john' with GitHub authenticator

        username = determine_username_from_uid(
            uid='different_uid',
            uid_filter=['john'],  # This UID exists but for GitHub, not LDAP
            email='different@example.com',  # Different email, won't merge
            authenticator=ldap_authenticator,
        )

        # Should create new unique username since no match and different email
        assert username != 'john'
        assert 'different_uid' in username or username == 'different_uid'
