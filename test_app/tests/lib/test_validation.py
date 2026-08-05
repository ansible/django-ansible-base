import pytest
from django.core.exceptions import ValidationError

from ansible_base.lib.validation import resource_name_validator


class TestValidateResourceName:
    """Test the resource_name_validator function."""

    # Valid names should pass validation
    @pytest.mark.parametrize(
        "name",
        [
            "simple",                           # basic word
            "My Production Organization",       # spaces
            "deploy-staging-2",                 # hyphens and numbers
            "user@domain.com",                  # @ and dots
            "_internal_name",                   # underscores
            "CamelCaseName",                    # mixed case
            "123numeric",                       # starts with number
            "mixed 123 name-with.all@types",    # kitchen sink
            "équipe",                           # unicode (French)
            "チーム名",                           # unicode (Japanese)
            "Проект",                           # unicode (Russian)
            "a",                                # single character
        ],
    )
    def test_valid_names(self, name):
        resource_name_validator(name)

    def test_accepts_max_length_name(self):
        # Exactly 512 characters (at the limit)
        max_name = "a" * 512
        resource_name_validator(max_name)

    # Security injection attacks should be rejected
    @pytest.mark.parametrize(
        "name",
        [
            "<script>alert(1)</script>",        # XSS
            '<img src=x onerror="alert(1)">',   # HTML injection
            "$(whoami)",                        # shell substitution
            "`id`",                             # backtick execution
            "name; rm -rf /",                   # shell command
            "'; DROP TABLE users--",           # SQL injection
            "1 OR 1=1",                         # SQL boolean bypass
            "name)(cn=*))(|(cn=*",             # LDAP injection
            "../../../etc/passwd",             # path traversal
            "/etc/shadow",                      # absolute path
            "name\x00injected",                # null byte injection
            "\x1b[31mred\x1b[0m",             # ANSI escape sequences
        ],
    )
    def test_rejects_injection_attacks(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    # Invalid patterns should be rejected
    @pytest.mark.parametrize(
        "name",
        [
            # Invalid starting characters
            " leading-space",                   # starts with space
            "-leading-hyphen",                  # starts with hyphen
            ".leading-dot",                     # starts with dot
            "@leading-at",                      # starts with @
            # Whitespace issues
            "valid-name\n",                     # trailing newline
            "line1\nline2",                     # embedded newline
            "name\twith\ttabs",                 # tab characters
        ],
    )
    def test_rejects_invalid_patterns(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            resource_name_validator("")

    def test_rejects_too_long_name(self):
        # 513 characters (1 over the 512 limit)
        long_name = "a" * 513
        with pytest.raises(ValidationError):
            resource_name_validator(long_name)

    # Error handling tests
    def test_error_message_is_descriptive(self):
        with pytest.raises(ValidationError) as exc_info:
            resource_name_validator("<script>")
        message = str(exc_info.value.message)
        assert "valid resource name" in message
        assert "letter, digit, or underscore" in message

    def test_error_code(self):
        with pytest.raises(ValidationError) as exc_info:
            resource_name_validator("<script>")
        assert exc_info.value.code == "invalid_resource_name"

    # Import path verification
    def test_importable_from_lib_validation(self):
        from ansible_base.lib.validation import resource_name_validator as validator

        assert validator is not None
        assert callable(validator)
