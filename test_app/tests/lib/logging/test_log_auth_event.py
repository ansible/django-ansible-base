import logging

import pytest
from django.test import override_settings

import ansible_base.lib.logging as logging_module
from ansible_base.lib.logging import log_auth_event


@pytest.fixture(autouse=True)
def reset_auth_logger():
    """Reset the global auth_logger before each test to ensure test isolation."""
    logging_module.auth_logger = None
    yield
    logging_module.auth_logger = None


class TestLogAuthEventBasicFunctionality:
    """Tests for basic logging functionality of log_auth_event."""

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


class TestLogAuthEventLoggerInitialization:
    """Tests for auth_logger initialization behavior."""

    def test_uses_default_logger_name_when_setting_not_configured(self, caplog):
        """Verify default logger name 'ansible_base.auth_audit' is used when no setting is configured."""
        with caplog.at_level(logging.INFO):
            log_auth_event("Test message")

        # The log should be captured under the default logger name
        assert any(r.name == 'ansible_base.auth_audit' for r in caplog.records)

    def test_uses_custom_logger_name_from_setting(self, caplog):
        """Verify custom logger name is used when ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME is set."""
        custom_logger_name = 'my_custom_auth_logger'

        with override_settings(ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME=custom_logger_name):
            with caplog.at_level(logging.INFO):
                log_auth_event("Custom logger test")

        # The log should be captured under the custom logger name
        assert any(r.name == custom_logger_name for r in caplog.records)

    def test_auth_logger_is_cached_after_first_call(self, caplog):
        """Verify that auth_logger is initialized once and reused on subsequent calls."""
        # First call initializes the logger
        with caplog.at_level(logging.INFO):
            log_auth_event("First message")

        # Capture the logger reference
        first_logger = logging_module.auth_logger

        # Second call should reuse the same logger
        with caplog.at_level(logging.INFO):
            log_auth_event("Second message")

        second_logger = logging_module.auth_logger

        # Both should be the same object
        assert first_logger is second_logger
        assert first_logger is not None

    def test_auth_logger_caching_ignores_subsequent_setting_changes(self, caplog):
        """Verify that once auth_logger is initialized, setting changes don't affect it."""
        # First call with default settings
        with caplog.at_level(logging.INFO):
            log_auth_event("Initial message")

        initial_logger = logging_module.auth_logger
        initial_logger_name = initial_logger.name

        # Now change the setting - but logger is already cached
        with override_settings(ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME='different_logger'):
            with caplog.at_level(logging.INFO):
                log_auth_event("After setting change")

        # Logger should still be the same (cached)
        assert logging_module.auth_logger is initial_logger
        assert logging_module.auth_logger.name == initial_logger_name


class TestLogAuthEventSecondLogger:
    """Tests for the optional second_logger parameter."""

    def test_logs_to_second_logger_when_provided(self, caplog):
        """Verify that message is logged to both auth_logger and second_logger."""
        second_logger = logging.getLogger('test.second.logger')

        with caplog.at_level(logging.INFO):
            log_auth_event("Dual logger message", second_logger=second_logger)

        # Should have logs from both loggers
        logger_names = [r.name for r in caplog.records]
        assert 'ansible_base.auth_audit' in logger_names
        assert 'test.second.logger' in logger_names

        # Both should have the same message
        messages = [r.message for r in caplog.records]
        assert messages.count("Dual logger message") == 2

    def test_does_not_log_to_second_logger_when_none(self, caplog):
        """Verify that only auth_logger receives message when second_logger is None."""
        with caplog.at_level(logging.INFO):
            log_auth_event("Single logger message", second_logger=None)

        # Should only have one log record
        assert len(caplog.records) == 1
        assert caplog.records[0].name == 'ansible_base.auth_audit'

    def test_does_not_log_to_second_logger_when_not_provided(self, caplog):
        """Verify default behavior (no second_logger) only logs to auth_logger."""
        with caplog.at_level(logging.INFO):
            log_auth_event("Default single logger message")

        # Should only have one log record
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

        # Should have auth_logger twice plus each second logger once
        assert logger_names.count('ansible_base.auth_audit') == 2
        assert logger_names.count('logger.a') == 1
        assert logger_names.count('logger.b') == 1


class TestLogAuthEventEdgeCases:
    """Tests for edge cases and boundary conditions."""

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
        long_message = "A" * 10000  # 10,000 character message

        with caplog.at_level(logging.INFO, logger='ansible_base.auth_audit'):
            log_auth_event(long_message)

        assert long_message in caplog.text

    def test_auth_logger_global_state_isolation(self):
        """Verify the global auth_logger can be properly reset for test isolation."""
        # The autouse fixture should have reset it
        assert logging_module.auth_logger is None

        # After a call, it should be set
        log_auth_event("Test")
        assert logging_module.auth_logger is not None

        # Manually reset (simulating what the fixture does)
        logging_module.auth_logger = None
        assert logging_module.auth_logger is None


class TestLogAuthEventIntegration:
    """Integration tests combining multiple features."""

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
