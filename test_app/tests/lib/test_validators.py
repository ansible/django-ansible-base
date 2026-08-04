import pytest
from django.core.exceptions import ValidationError

from ansible_base.lib.validators import resource_name_validator


class TestResourceNameValidatorAcceptsValidNames:
    """Valid names should pass validation without raising."""

    @pytest.mark.parametrize(
        "name",
        [
            "My Production Organization",
            "deploy-staging-2",
            "test_project.01",
            "a",
            "A",
            "0",
            "_",
            "org with spaces",
            "user@domain",
            "my.org.name",
            "simple",
            "CamelCaseName",
            "UPPER_CASE",
            "name-with-hyphens",
            "under_score_name",
            "123numeric",
            "mixed 123 name-with.all@types",
        ],
        ids=lambda v: f"ascii:{v[:30]}",
    )
    def test_valid_ascii_names(self, name):
        resource_name_validator(name)

    @pytest.mark.parametrize(
        "name",
        [
            "équipe",
            "チーム名",
            "Проект",
            "مشروع",
            "프로젝트",
            "Café Org",
            "Über Team",
            "Résumé Builder",
            "中文组织",
            "ⅰⅱⅲ",
        ],
        ids=[
            "french-accented",
            "japanese-katakana",
            "russian-cyrillic",
            "arabic",
            "korean",
            "mixed-latin-accent",
            "german-umlaut",
            "multi-accent",
            "chinese",
            "roman-numerals",
        ],
    )
    def test_valid_unicode_names(self, name):
        resource_name_validator(name)


class TestResourceNameValidatorRejectsInjection:
    """Injection payloads must be rejected."""

    @pytest.mark.parametrize(
        "name",
        [
            "<script>alert(1)</script>",
            '<img src=x onerror="alert(1)">',
            "org<b>bold</b>",
            "name<div>test</div>",
            "<a href='http://evil.com'>click</a>",
        ],
        ids=[
            "script-tag",
            "img-onerror",
            "inline-bold-tag",
            "div-tag",
            "anchor-tag",
        ],
    )
    def test_rejects_html_injection(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    @pytest.mark.parametrize(
        "name",
        [
            "$(whoami)",
            "`id`",
            "name; rm -rf /",
            "$(cat /etc/passwd)",
            "name | cat /etc/shadow",
            "name && echo pwned",
            "name || true",
        ],
        ids=[
            "dollar-paren",
            "backtick",
            "semicolon-cmd",
            "dollar-paren-cat",
            "pipe-cmd",
            "double-ampersand",
            "double-pipe",
        ],
    )
    def test_rejects_shell_substitution(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    @pytest.mark.parametrize(
        "name",
        [
            "'; DROP TABLE users--",
            "1 OR 1=1",
            "admin'--",
            "name' UNION SELECT * FROM credentials--",
        ],
        ids=[
            "drop-table",
            "or-1-equals-1",
            "comment-bypass",
            "union-select",
        ],
    )
    def test_rejects_sql_injection(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    @pytest.mark.parametrize(
        "name",
        [
            "name)(cn=*))(|(cn=*",
            "admin)(&)",
            "*()|&",
        ],
        ids=[
            "ldap-filter-injection",
            "ldap-and-bypass",
            "ldap-wildcard",
        ],
    )
    def test_rejects_ldap_injection(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    @pytest.mark.parametrize(
        "name",
        [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/shadow",
            "....",
            ".hidden",
        ],
        ids=[
            "unix-traversal",
            "windows-traversal",
            "absolute-path",
            "dot-sequence",
            "dot-prefix",
        ],
    )
    def test_rejects_path_traversal(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    @pytest.mark.parametrize(
        "name",
        [
            "name\x00injected",
            "\x00",
            "before\x00after",
        ],
        ids=[
            "null-mid",
            "null-only",
            "null-between-words",
        ],
    )
    def test_rejects_null_bytes(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    @pytest.mark.parametrize(
        "name",
        [
            "\x1b[31mred\x1b[0m",
            "name\x1b[0m",
            "\x07bell",
        ],
        ids=[
            "ansi-color",
            "ansi-reset",
            "bell-char",
        ],
    )
    def test_rejects_ansi_escapes(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)


class TestResourceNameValidatorEdgeCases:
    """Edge cases and boundary conditions."""

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            resource_name_validator("")

    @pytest.mark.parametrize(
        "name",
        [
            " leading-space",
            "-leading-hyphen",
            ".leading-dot",
            "@leading-at",
        ],
        ids=[
            "space-start",
            "hyphen-start",
            "dot-start",
            "at-start",
        ],
    )
    def test_rejects_non_word_char_start(self, name):
        with pytest.raises(ValidationError):
            resource_name_validator(name)

    def test_rejects_trailing_newline(self):
        with pytest.raises(ValidationError):
            resource_name_validator("valid-name\n")

    def test_rejects_embedded_newline(self):
        with pytest.raises(ValidationError):
            resource_name_validator("line1\nline2")

    def test_rejects_tab(self):
        with pytest.raises(ValidationError):
            resource_name_validator("name\twith\ttabs")

    def test_single_word_char(self):
        resource_name_validator("a")

    def test_single_unicode_char(self):
        resource_name_validator("é")

    def test_single_digit(self):
        resource_name_validator("5")

    def test_single_underscore(self):
        resource_name_validator("_")


class TestResourceNameValidatorErrorMessage:
    """The error message should be clear and descriptive."""

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


class TestResourceNameValidatorImportPath:
    """Verify the public import path works."""

    def test_importable_from_lib_validators(self):
        from ansible_base.lib.validators import resource_name_validator as validator

        assert validator is not None
        assert callable(validator)
