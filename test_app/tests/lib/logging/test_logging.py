import logging
from unittest import mock

import pytest
from django.test import override_settings

import ansible_base.lib.logging as logging_module
from ansible_base.lib.logging import get_auth_logger, log_auth_event, log_auth_exception, log_auth_warning


@pytest.fixture(autouse=True)
def reset_auth_logger():
    """Reset the global auth_logger before each test to ensure test isolation."""
    logging_module.auth_logger = None
    yield
    logging_module.auth_logger = None


class TestGetAuthLogger:
    """Tests for get_auth_logger function."""

    @mock.patch("ansible_base.lib.logging.get_setting")
    @mock.patch("ansible_base.lib.logging.logging.getLogger")
    def test_uses_configured_logger_name(self, mock_get_logger, mock_get_setting):
        """Test that get_auth_logger uses the configured logger name from settings."""
        mock_get_setting.return_value = "custom.auth.logger"
        mock_logger = mock.Mock()
        mock_get_logger.return_value = mock_logger

        result = get_auth_logger()

        mock_get_setting.assert_called_once_with('ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME', 'ansible_base.auth_audit')
        mock_get_logger.assert_called_once_with("custom.auth.logger")
        assert result == mock_logger

    @mock.patch("ansible_base.lib.logging.get_setting")
    @mock.patch("ansible_base.lib.logging.logging.getLogger")
    def test_uses_default_logger_name(self, mock_get_logger, mock_get_setting):
        """Test that get_auth_logger uses the default logger name when not configured."""
        mock_get_setting.return_value = 'ansible_base.auth_audit'
        mock_logger = mock.Mock()
        mock_get_logger.return_value = mock_logger

        result = get_auth_logger()

        mock_get_setting.assert_called_once_with('ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME', 'ansible_base.auth_audit')
        mock_get_logger.assert_called_once_with('ansible_base.auth_audit')
        assert result == mock_logger


class TestLogAuthEvent:
    """Tests for log_auth_event function."""

    def test_logs_message_to_auth_logger(self, caplog):
        """Verify that the message is logged to the auth_logger at INFO level."""
        with caplog.at_level(logging.INFO, logger='ansible_base.auth_audit'):
            log_auth_event("User logged in successfully")

        assert "User logged in successfully" in caplog.text
        assert any(record.levelno == logging.INFO for record in caplog.records)

    def test_logs_with_correct_logger_name(self, caplog):
        """Verify that logs come from the expected logger name."""
        with caplog.at_level(logging.INFO):
            log_auth_event("Test authentication event")

        auth_records = [r for r in caplog.records if r.name == 'ansible_base.auth_audit']
        assert len(auth_records) == 1
        assert auth_records[0].message == "Test authentication event"

    @pytest.mark.parametrize(
        "message",
        [
            "Simple message",
            "Message with special characters: !@#$%^&*()",
            "Message with unicode: 日本語 中文 한국어",
            "",  # Empty message
            "   ",  # Whitespace only
            "Multi\nline\nmessage",
        ],
    )
    def test_logs_various_message_formats(self, caplog, message):
        """Verify that various message formats are logged correctly."""
        with caplog.at_level(logging.INFO, logger='ansible_base.auth_audit'):
            log_auth_event(message)

        assert message in caplog.text

    def test_uses_default_logger_name_when_setting_not_configured(self, caplog):
        """Verify default logger name 'ansible_base.auth_audit' is used when no setting is configured."""
        with caplog.at_level(logging.INFO):
            log_auth_event("Test message")

        assert any(r.name == 'ansible_base.auth_audit' for r in caplog.records)

    def test_uses_custom_logger_name_from_setting(self, caplog):
        """Verify custom logger name is used when ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME is set."""
        custom_logger_name = 'my_custom_auth_logger'

        with override_settings(ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME=custom_logger_name):
            with caplog.at_level(logging.INFO):
                log_auth_event("Custom logger test")

        assert any(r.name == custom_logger_name for r in caplog.records)

    def test_auth_logger_is_cached_after_first_call(self, caplog):
        """Verify that auth_logger is initialized once and reused on subsequent calls."""
        with caplog.at_level(logging.INFO):
            log_auth_event("First message")

        first_logger = logging_module.auth_logger

        with caplog.at_level(logging.INFO):
            log_auth_event("Second message")

        second_logger = logging_module.auth_logger

        assert first_logger is second_logger
        assert first_logger is not None

    def test_auth_logger_caching_ignores_subsequent_setting_changes(self, caplog):
        """Verify that once auth_logger is initialized, setting changes don't affect it."""
        with caplog.at_level(logging.INFO):
            log_auth_event("Initial message")

        initial_logger = logging_module.auth_logger
        initial_logger_name = initial_logger.name

        with override_settings(ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME='different_logger'):
            with caplog.at_level(logging.INFO):
                log_auth_event("After setting change")

        assert logging_module.auth_logger is initial_logger
        assert logging_module.auth_logger.name == initial_logger_name

    def test_logs_to_second_logger_when_provided(self, caplog):
        """Verify that message is logged to both auth_logger and second_logger."""
        second_logger = logging.getLogger('test.second.logger')

        with caplog.at_level(logging.INFO):
            log_auth_event("Dual logger message", second_logger=second_logger)

        logger_names = [r.name for r in caplog.records]
        assert 'ansible_base.auth_audit' in logger_names
        assert 'test.second.logger' in logger_names

        messages = [r.message for r in caplog.records]
        assert messages.count("Dual logger message") == 2

    def test_does_not_log_to_second_logger_when_none(self, caplog):
        """Verify that only auth_logger receives message when second_logger is None."""
        with caplog.at_level(logging.INFO):
            log_auth_event("Single logger message", second_logger=None)

        assert len(caplog.records) == 1
        assert caplog.records[0].name == 'ansible_base.auth_audit'

    def test_does_not_log_to_second_logger_when_not_provided(self, caplog):
        """Verify default behavior (no second_logger) only logs to auth_logger."""
        with caplog.at_level(logging.INFO):
            log_auth_event("Default single logger message")

        assert len(caplog.records) == 1
        assert caplog.records[0].name == 'ansible_base.auth_audit'

    def test_second_logger_receives_info_level_message(self, caplog):
        """Verify that second_logger receives message at INFO level."""
        second_logger = logging.getLogger('test.level.logger')

        with caplog.at_level(logging.INFO):
            log_auth_event("Level test message", second_logger=second_logger)

        second_logger_records = [r for r in caplog.records if r.name == 'test.level.logger']
        assert len(second_logger_records) == 1
        assert second_logger_records[0].levelno == logging.INFO

    def test_different_second_loggers_on_consecutive_calls(self, caplog):
        """Verify that different second_loggers can be used on consecutive calls."""
        logger_a = logging.getLogger('logger.a')
        logger_b = logging.getLogger('logger.b')

        with caplog.at_level(logging.INFO):
            log_auth_event("Message A", second_logger=logger_a)
            log_auth_event("Message B", second_logger=logger_b)

        logger_names = [r.name for r in caplog.records]

        assert logger_names.count('ansible_base.auth_audit') == 2
        assert logger_names.count('logger.a') == 1
        assert logger_names.count('logger.b') == 1

    def test_multiple_calls_all_logged(self, caplog):
        """Verify that multiple consecutive calls all result in logged messages."""
        messages = ["First auth event", "Second auth event", "Third auth event"]

        with caplog.at_level(logging.INFO, logger='ansible_base.auth_audit'):
            for msg in messages:
                log_auth_event(msg)

        for msg in messages:
            assert msg in caplog.text

    def test_logs_long_message(self, caplog):
        """Verify that very long messages are logged correctly."""
        long_message = "A" * 10000

        with caplog.at_level(logging.INFO, logger='ansible_base.auth_audit'):
            log_auth_event(long_message)

        assert long_message in caplog.text

    def test_auth_logger_global_state_isolation(self):
        """Verify the global auth_logger can be properly reset for test isolation."""
        assert logging_module.auth_logger is None

        log_auth_event("Test")
        assert logging_module.auth_logger is not None

        logging_module.auth_logger = None
        assert logging_module.auth_logger is None

    def test_custom_logger_name_with_second_logger(self, caplog):
        """Verify custom logger name works correctly with second_logger."""
        custom_name = 'custom.auth.audit'
        second_logger = logging.getLogger('integration.second')

        with override_settings(ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME=custom_name):
            with caplog.at_level(logging.INFO):
                log_auth_event("Integration test message", second_logger=second_logger)

        logger_names = [r.name for r in caplog.records]
        assert custom_name in logger_names
        assert 'integration.second' in logger_names
        assert len(caplog.records) == 2

    def test_realistic_auth_event_messages(self, caplog):
        """Test with realistic authentication event messages."""
        test_messages = [
            "User 'admin' successfully authenticated via LDAP",
            "Failed login attempt for user 'unknown_user' from IP 192.168.1.100",
            "User 'john.doe@example.com' logged out",
            "Token refresh for user 'service_account'",
            "Password changed for user 'admin'",
            "MFA verification successful for user 'secure_user'",
        ]

        with caplog.at_level(logging.INFO, logger='ansible_base.auth_audit'):
            for msg in test_messages:
                log_auth_event(msg)

        for msg in test_messages:
            assert msg in caplog.text

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_logs_to_auth_logger_mock(self, mock_get_auth_logger):
        """Test that log_auth_event logs info to the auth logger using mocks."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger

        log_auth_event("Test event message")

        mock_auth_logger.log.assert_called_once_with(logging.INFO, "Test event message")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_logs_to_second_logger_mock(self, mock_get_auth_logger):
        """Test that log_auth_event logs info to both auth logger and second logger using mocks."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger
        mock_second_logger = mock.Mock()

        log_auth_event("Test event message", second_logger=mock_second_logger)

        mock_auth_logger.log.assert_called_once_with(logging.INFO, "Test event message")
        mock_second_logger.log.assert_called_once_with(logging.INFO, "Test event message")


class TestLogAuthWarning:
    """Tests for log_auth_warning function."""

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_logs_to_auth_logger(self, mock_get_auth_logger):
        """Test that log_auth_warning logs warning to the auth logger."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger

        log_auth_warning("Test warning message")

        mock_auth_logger.log.assert_called_once_with(logging.WARNING, "Test warning message")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_logs_to_second_logger(self, mock_get_auth_logger):
        """Test that log_auth_warning logs warning to both auth logger and second logger."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger
        mock_second_logger = mock.Mock()

        log_auth_warning("Test warning message", second_logger=mock_second_logger)

        mock_auth_logger.log.assert_called_once_with(logging.WARNING, "Test warning message")
        mock_second_logger.log.assert_called_once_with(logging.WARNING, "Test warning message")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_only_logs_to_auth_logger_when_no_second_logger(self, mock_get_auth_logger):
        """Test that log_auth_warning only logs to auth logger when second_logger is None."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger

        log_auth_warning("Test warning message", second_logger=None)

        mock_auth_logger.log.assert_called_once_with(logging.WARNING, "Test warning message")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_with_empty_message(self, mock_get_auth_logger):
        """Test that log_auth_warning handles empty messages."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger

        log_auth_warning("")

        mock_auth_logger.log.assert_called_once_with(logging.WARNING, "")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_with_multiline_message(self, mock_get_auth_logger):
        """Test that log_auth_warning handles multiline messages."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger
        multiline_message = "Line 1\nLine 2\nLine 3"

        log_auth_warning(multiline_message)

        mock_auth_logger.log.assert_called_once_with(logging.WARNING, multiline_message)

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_with_special_characters(self, mock_get_auth_logger):
        """Test that log_auth_warning handles messages with special characters."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger
        special_message = "Warning: User 'admin@example.com' failed auth {attempt: 3}"

        log_auth_warning(special_message)

        mock_auth_logger.log.assert_called_once_with(logging.WARNING, special_message)


class TestLogAuthException:
    """Tests for log_auth_exception function."""

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_logs_to_auth_logger(self, mock_get_auth_logger):
        """Test that log_auth_exception logs exception to the auth logger."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger

        log_auth_exception("Test exception message")

        mock_auth_logger.exception.assert_called_once_with("Test exception message")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_logs_to_second_logger(self, mock_get_auth_logger):
        """Test that log_auth_exception logs exception to both auth logger and second logger."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger
        mock_second_logger = mock.Mock()

        log_auth_exception("Test exception message", second_logger=mock_second_logger)

        mock_auth_logger.exception.assert_called_once_with("Test exception message")
        mock_second_logger.exception.assert_called_once_with("Test exception message")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_only_logs_to_auth_logger_when_no_second_logger(self, mock_get_auth_logger):
        """Test that log_auth_exception only logs to auth logger when second_logger is None."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger

        log_auth_exception("Test exception message", second_logger=None)

        mock_auth_logger.exception.assert_called_once_with("Test exception message")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_with_empty_message(self, mock_get_auth_logger):
        """Test that log_auth_exception handles empty messages."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger

        log_auth_exception("")

        mock_auth_logger.exception.assert_called_once_with("")

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_with_multiline_message(self, mock_get_auth_logger):
        """Test that log_auth_exception handles multiline messages."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger
        multiline_message = "Error occurred:\nTraceback details\nMore info"

        log_auth_exception(multiline_message)

        mock_auth_logger.exception.assert_called_once_with(multiline_message)

    @mock.patch("ansible_base.lib.logging.get_auth_logger")
    def test_with_special_characters(self, mock_get_auth_logger):
        """Test that log_auth_exception handles messages with special characters."""
        mock_auth_logger = mock.Mock()
        mock_get_auth_logger.return_value = mock_auth_logger
        special_message = "Exception: Token 'abc-123' @ /api/v1/users/"

        log_auth_exception(special_message)

        mock_auth_logger.exception.assert_called_once_with(special_message)
