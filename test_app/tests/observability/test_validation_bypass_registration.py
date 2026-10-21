"""Observability app wires DAB validation bypass signal registration."""

from ansible_base.observability.apps import ObservabilityConfig


def test_ready_registers_validation_bypass_logging(mocker):
    mocker.patch('ansible_base.observability.apps.setup_observability')
    register = mocker.patch(
        'ansible_base.lib.utils.validation_signals.register_validation_signals',
    )

    config = ObservabilityConfig.create('ansible_base.observability')
    config.ready()

    register.assert_called_once()
