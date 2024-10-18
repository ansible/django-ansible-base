from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.db.models import CharField, Model


@pytest.mark.parametrize(
    'exception_type,message',
    [
        (FileNotFoundError, "does not exist"),
        (PermissionError, "No permission to read"),
        (IndexError, "Failed to read"),
    ],
)
def test_exception_on_ignore_file_read(exception_type, message):
    out = StringIO()
    err = StringIO()

    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        mock_file.side_effect = exception_type('Testing perm error')
        with pytest.raises(SystemExit) as pytest_wrapped_e:
            call_command('help_text_check', ignore_file='junk.dne', stdout=out, stderr=err)

    assert pytest_wrapped_e.value.code == 255
    assert message in err.getvalue()


@pytest.mark.parametrize(
    "read_data,has_message",
    [
        ('', False),
        ('asdf', True),
    ],
)
def test_valid_exception_types(read_data, has_message):
    out = StringIO()
    err = StringIO()

    with mock.patch('ansible_base.help_text_check.management.commands.help_text_check.apps.get_models', return_value=[]):
        with mock.patch("builtins.open", mock.mock_open(read_data=read_data)):
            with pytest.raises(SystemExit) as pytest_wrapped_e:
                call_command('help_text_check', ignore_file='junk.dne', stdout=out, stderr=err)

    assert pytest_wrapped_e.value.code == 0
    if has_message:
        assert 'Ignoring 1 field(s)' in out.getvalue()
    else:
        assert 'Ignoring' not in out.getvalue()


def test_missing_application():
    out = StringIO()
    err = StringIO()

    with pytest.raises(SystemExit) as pytest_wrapped_e:
        call_command('help_text_check', applications='App3', stdout=out, stderr=err)

    assert pytest_wrapped_e.value.code == 0
    assert 'is not in INSTALLED_APPS' in err.getvalue()


def get_app_config_mock(app_name):
    class mock_app_config:
        def __init__(self, app_name):
            self.app_name = app_name

        def get_models(self):
            if self.app_name == 'App1':
                return ['App1.model1', 'App1.model2', 'App1.model1']
            elif self.app_name == 'App2':
                return ['App2.model1']
            else:
                raise Exception("This has to be called with either App1 or App2")

    return mock_app_config(app_name)


def test_app_limit():
    from ansible_base.help_text_check.management.commands.help_text_check import Command

    command = Command()

    with mock.patch.dict('ansible_base.help_text_check.management.commands.help_text_check.apps.app_configs', {'App1': [], 'App2': [], 'App3': []}):
        with mock.patch('ansible_base.help_text_check.management.commands.help_text_check.apps.get_app_config') as get_app_config:
            get_app_config.side_effect = get_app_config_mock
            models = command.get_models('App1,App2')
            assert models == ['App1.model1', 'App1.model2', 'App2.model1']


class GoodModel(Model):
    class Meta:
        app_label = 'Testing'

    test_field = CharField(
        help_text='Testing help_text',
    )


class BadModel(Model):
    class Meta:
        app_label = 'Testing'

    test_field = CharField()


def get_app_config_actual_models(app_name):
    class mock_app_config:
        def __init__(self, app_name):
            self.app_name = app_name

        def get_models(self):
            if app_name == 'good':
                return [GoodModel]
            elif app_name == 'bad':
                return [BadModel]
            else:
                return [GoodModel, BadModel]

    return mock_app_config(app_name)


@pytest.mark.parametrize(
    'test_type',
    [
        "good",
        "bad",
    ],
)
def test_models(test_type):
    out = StringIO()
    err = StringIO()

    with mock.patch.dict('ansible_base.help_text_check.management.commands.help_text_check.apps.app_configs', {test_type: []}):
        with mock.patch('ansible_base.help_text_check.management.commands.help_text_check.apps.get_app_config') as get_app_config:
            get_app_config.side_effect = get_app_config_actual_models
            with pytest.raises(SystemExit) as pytest_wrapped_e:
                call_command('help_text_check', applications=test_type, stdout=out, stderr=err)

    if test_type == 'good':
        assert pytest_wrapped_e.value.code == 0
        assert 'Testing.GoodModel' in out.getvalue()
        assert 'Testing help_text' in out.getvalue()
    elif test_type == 'bad':
        assert pytest_wrapped_e.value.code == 1
        assert 'Testing.BadModel' in out.getvalue()
        assert 'test_field: missing help_text' in out.getvalue()
    else:
        assert False, "This test can only do good and bad models right now"
