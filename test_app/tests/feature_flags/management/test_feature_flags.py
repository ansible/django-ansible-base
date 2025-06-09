import io
from unittest import mock

import pytest
from django.conf import settings  # Import settings
from django.core.management import call_command

# Ensure settings are configured before importing models or command
if not settings.configured:
    settings.configure()  # Minimal configuration for tests


class MockAAPFlag:
    def __init__(self, name, ui_name, value, support_level, visibility, toggle_type, description, support_url):
        self.name = name
        self.ui_name = ui_name
        self.value = value
        self.support_level = support_level
        self.visibility = visibility
        self.toggle_type = toggle_type
        self.description = description
        self.support_url = support_url

    def __str__(self):
        return self.name


HAS_TABULATE_PATH = 'ansible_base.feature_flags.management.commands.feature_flags.HAS_TABULATE'
COMMAND_MODULE_PATH = 'ansible_base.feature_flags.management.commands.feature_flags'


@pytest.fixture
def mock_flags_data():
    return [
        MockAAPFlag(
            name="flag1",
            ui_name="Flag One",
            value=True,
            support_level="supported",
            visibility="public",
            toggle_type="boolean",
            description="Description for flag one",
            support_url="http://example.com/flag1",
        ),
        MockAAPFlag(
            name="flag2",
            ui_name="Flag Two",
            value=False,
            support_level="experimental",
            visibility="internal",
            toggle_type="string",
            description="Description for flag two",
            support_url="http://example.com/flag2",
        ),
    ]


@pytest.mark.django_db(transaction=False)
@mock.patch(f'{COMMAND_MODULE_PATH}.flag_state')
@mock.patch(f'{COMMAND_MODULE_PATH}.AAPFlag.objects')
def test_list_feature_flags_with_tabulate(mock_aap_flag_objects, mock_flag_state, mock_flags_data, capsys):
    mock_aap_flag_objects.all.return_value.order_by.return_value = mock_flags_data

    mock_flag_state.side_effect = lambda name: next(f.value for f in mock_flags_data if f.name == name)

    with mock.patch(HAS_TABULATE_PATH, True):  # Simulate tabulate is installed
        with mock.patch(f'{COMMAND_MODULE_PATH}.tabulate') as mock_tabulate_func:
            # Mock the tabulate function to check its call and control its output for simplicity
            # or let it run if you want to test its actual output formatting
            mock_tabulate_func.return_value = "mocked_tabulate_output"

            call_command('feature_flags', '--list')

            captured = capsys.readouterr()

            # Check headers (they are part of the data passed to tabulate)
            expected_headers = ["Name", "UI_Name", "Value", "State", "Support Level", "Visibility", "Toggle Type", "Description", "Support URL"]

            # Check that tabulate was called
            assert mock_tabulate_func.called

            # Check the arguments passed to tabulate
            args, kwargs = mock_tabulate_func.call_args
            passed_data = args[0]
            passed_headers = args[1]
            passed_tablefmt = kwargs.get('tablefmt')

            assert passed_headers == expected_headers
            assert passed_tablefmt == "github"

            assert len(passed_data) == 2
            assert passed_data[0] == [
                'flag1',
                'Flag One',
                'True',
                'True',
                'supported',
                'public',
                'boolean',
                'Description for flag one',
                'http://example.com/flag1',
            ]
            assert passed_data[1] == [
                'flag2',
                'Flag Two',
                'False',
                'False',
                'experimental',
                'internal',
                'string',
                'Description for flag two',
                'http://example.com/flag2',
            ]

            assert "mocked_tabulate_output" in captured.out
            assert captured.out.strip() == "mocked_tabulate_output"


@pytest.mark.django_db(transaction=False)
@mock.patch(f'{COMMAND_MODULE_PATH}.flag_state')
@mock.patch(f'{COMMAND_MODULE_PATH}.AAPFlag.objects')
def test_list_feature_flags_without_tabulate(mock_aap_flag_objects, mock_flag_state, mock_flags_data, capsys):
    mock_aap_flag_objects.all.return_value.order_by.return_value = mock_flags_data
    mock_flag_state.side_effect = lambda name: next(f.value for f in mock_flags_data if f.name == name)

    with mock.patch(HAS_TABULATE_PATH, False):  # Simulate tabulate is NOT installed
        call_command('feature_flags', '--list')

        captured = capsys.readouterr()
        output_lines = captured.out.strip().split('\n')

        expected_headers_str = "\t".join(["Name", "UI_Name", "Value", "State", "Support Level", "Visibility", "Toggle Type", "Description", "Support URL"])

        assert output_lines[0] == expected_headers_str

        expected_data_row1 = "\t".join(
            ['flag1', 'Flag One', 'True', 'True', 'supported', 'public', 'boolean', 'Description for flag one', 'http://example.com/flag1']
        )
        expected_data_row2 = "\t".join(
            ['flag2', 'Flag Two', 'False', 'False', 'experimental', 'internal', 'string', 'Description for flag two', 'http://example.com/flag2']
        )

        assert output_lines[1] == expected_data_row1
        assert output_lines[2] == expected_data_row2
        assert len(output_lines) == 3  # Headers + 2 data rows


@pytest.mark.django_db(transaction=False)
@mock.patch(f'{COMMAND_MODULE_PATH}.flag_state')  # Still need to mock this even if no flags
@mock.patch(f'{COMMAND_MODULE_PATH}.AAPFlag.objects')
def test_list_feature_flags_no_flags_with_tabulate(mock_aap_flag_objects, mock_flag_state, capsys):
    mock_aap_flag_objects.all.return_value.order_by.return_value = []  # No flags

    with mock.patch(HAS_TABULATE_PATH, True):
        with mock.patch(f'{COMMAND_MODULE_PATH}.tabulate') as mock_tabulate_func:
            mock_tabulate_func.return_value = "mocked_empty_table"

            call_command('feature_flags', '--list')

            captured = capsys.readouterr()

            assert mock_tabulate_func.called
            args, kwargs = mock_tabulate_func.call_args
            assert args[0] == []
            assert args[1] == ["Name", "UI_Name", "Value", "State", "Support Level", "Visibility", "Toggle Type", "Description", "Support URL"]
            assert kwargs.get('tablefmt') == "github"

            assert "mocked_empty_table" in captured.out.strip()


@pytest.mark.django_db(transaction=False)
@mock.patch(f'{COMMAND_MODULE_PATH}.flag_state')
@mock.patch(f'{COMMAND_MODULE_PATH}.AAPFlag.objects')
def test_list_feature_flags_no_flags_without_tabulate(mock_aap_flag_objects, mock_flag_state, capsys):
    mock_aap_flag_objects.all.return_value.order_by.return_value = []  # No flags

    with mock.patch(HAS_TABULATE_PATH, False):
        call_command('feature_flags', '--list')

        captured = capsys.readouterr()
        output_lines = captured.out.strip().split('\n')

        expected_headers_str = "\t".join(["Name", "UI_Name", "Value", "State", "Support Level", "Visibility", "Toggle Type", "Description", "Support URL"])

        assert output_lines[0] == expected_headers_str
        assert len(output_lines) == 1  # Only headers


def test_handle_no_options():
    # This test is to ensure that if no options (like --list) are passed,
    # the command doesn't error out and list_feature_flags is not called.
    # We expect it to do nothing based on the provided handle method.
    stdout = io.StringIO()
    stderr = io.StringIO()

    # Patch list_feature_flags to ensure it's not called
    with mock.patch(f'{COMMAND_MODULE_PATH}.Command.list_feature_flags') as mock_list_method:
        call_command('feature_flags', stdout=stdout, stderr=stderr)  # No arguments
        mock_list_method.assert_not_called()
        assert stdout.getvalue() == ""
        assert stderr.getvalue() == ""


@pytest.mark.django_db
def test_management_command_existing_data(aap_flags, capsys):
    from ansible_base.feature_flags.utils import feature_flags_list

    call_command('feature_flags', '--list')

    captured = capsys.readouterr()
    output_lines = captured.out.strip().split('\n')
    assert len(output_lines) - 2 == len(feature_flags_list())  # Subtract 2 to remove header and '---' line before data
