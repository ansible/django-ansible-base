def test_settings_override_mutable(settings_override_mutable, settings):
    """
    Ensure that when we modify a mutable setting, it gets reverted.
    """
    assert settings.LOGGING['handlers']['console']['formatter'] == "simple"

    with settings_override_mutable('LOGGING'):
        settings.LOGGING['handlers']['console']['formatter'] = "not so simple"
        assert settings.LOGGING['handlers']['console']['formatter'] == "not so simple"

        del settings.LOGGING['handlers']['console']['formatter']
        assert 'formattter' not in settings.LOGGING['handlers']['console']

    assert settings.LOGGING['handlers']['console']['formatter'] == "simple"
