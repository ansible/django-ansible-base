import json
from unittest.mock import MagicMock, call

import pytest
import yaml
from django.core.exceptions import ValidationError
from jsonschema import validate

MODULE_PATH = "ansible_base.feature_flags.utils"


# Mock the AAPFlag model structure that apps.get_model would return
# and instances that the model manager would operate on.
class MockAAPFlagInstance:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name')
        self.condition = kwargs.get('condition')
        self.value = kwargs.get('value')
        self.support_level = kwargs.get('support_level')
        self.visibility = kwargs.get('visibility')
        self.ui_name = kwargs.get('ui_name')
        self.support_url = kwargs.get('support_url')
        self.required = kwargs.get('required', False)
        self.toggle_type = kwargs.get('toggle_type', 'run-time')
        self.labels = kwargs.get('labels', [])
        self.description = kwargs.get('description', '')
        # Add save, full_clean, delete methods that can be spied on or controlled
        self.save = MagicMock()
        self.full_clean = MagicMock()
        self.delete = MagicMock()

    # To allow attribute setting like existing.support_level = ...
    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        if key not in ['save', 'full_clean', 'delete']:
            pass


@pytest.fixture
def mock_aap_flag_model_cls(mocker):
    model_class = MagicMock(spec_set=['objects'])

    def model_constructor(**kwargs):
        instance = MockAAPFlagInstance(**kwargs)
        instance.save = mocker.MagicMock()
        instance.full_clean = mocker.MagicMock()
        instance.delete = mocker.MagicMock()
        return instance

    model_class.side_effect = model_constructor
    model_class.return_value = MagicMock(spec=MockAAPFlagInstance)

    # Mock the manager
    model_class.objects = MagicMock()
    model_class.objects.all = MagicMock()
    model_class.objects.filter = MagicMock()

    return model_class


@pytest.fixture
def mock_apps_get_model(mocker, mock_aap_flag_model_cls):
    return mocker.patch(f"{MODULE_PATH}.apps.get_model", return_value=mock_aap_flag_model_cls)


@pytest.fixture
def mock_settings(mocker):
    # Patch 'settings' within the utils module
    mocked_settings = mocker.patch(f"{MODULE_PATH}.settings")

    # This dictionary will hold the "true" values for our settings attributes.
    _settings_attrs = {}

    def _hasattr_callable(name):
        return name in _settings_attrs

    def _getattr_callable(name):
        if name in _settings_attrs:
            return _settings_attrs[name]
        raise AttributeError(f"Mock settings has no attribute {name}")

    # Configure the 'hasattr' and 'getattr' attributes on the mocked_settings object.
    # This is for when the code explicitly calls settings.hasattr(...) or settings.getattr(...).
    mocked_settings.hasattr = mocker.MagicMock(side_effect=_hasattr_callable)
    mocked_settings.getattr = mocker.MagicMock(side_effect=_getattr_callable)

    def set_settings_attr(name, value):
        # Store the attribute in our local dictionary
        _settings_attrs[name] = value
        setattr(mocked_settings, name, value)
        # Update the side effects for the callable attributes 'hasattr' and 'getattr'
        # to use the latest state of _settings_attrs.
        mocked_settings.hasattr.side_effect = lambda n: n in _settings_attrs
        mocked_settings.getattr.side_effect = lambda n: (_settings_attrs[n] if n in _settings_attrs else AttributeError(f"Mock settings has no attribute {n}"))

    mocked_settings.set_attr = set_settings_attr
    return mocked_settings


@pytest.fixture
def mock_logger(mocker):
    logger_instance = mocker.MagicMock()
    mocker.patch(f"{MODULE_PATH}.logger", logger_instance)
    return logger_instance


@pytest.fixture
def mock_feature_flags_list(mocker):
    mock = mocker.patch(f"{MODULE_PATH}.feature_flags_list")
    return mock


def test_get_django_flags(mocker):
    from ansible_base.feature_flags.utils import get_django_flags

    mock_internal_get_flags = mocker.patch(f"{MODULE_PATH}.get_flags")
    mock_internal_get_flags.return_value = {"FLAG_X": True}

    result = get_django_flags()

    mock_internal_get_flags.assert_called_once()
    assert result == {"FLAG_X": True}


def test_validate_flags_yaml_against_json_schema():
    feature_flags_yaml = 'ansible_base/feature_flags/definitions/feature_flags.yaml'
    feature_flags_schema = 'ansible_base/feature_flags/definitions/schema.json'
    try:
        with open(feature_flags_yaml, 'r') as file:
            feature_flags_file = yaml.safe_load(file)
        with open(feature_flags_schema, 'r') as file:
            schema = json.load(file)
        validate(instance=feature_flags_file, schema=schema)
        # Test passes if no exception is raised during validation
    except FileNotFoundError as e:
        pytest.fail(f"Could not find a necessary file: {e}. Make sure schema.json and valid_data.yaml exist.")
    except Exception as e:
        # If any other exception occurs (like a ValidationError), fail the test.
        pytest.fail(f"Validation failed unexpectedly for a valid file: {e}")


class TestCreateInitialData:

    @pytest.mark.django_db  # May not be strictly necessary with all the mocking, but good practice
    def test_load_feature_flags_creates_new_flag_from_settings_value(
        self, mock_apps_get_model, mock_aap_flag_model_cls, mock_settings, mock_logger, mock_feature_flags_list, mocker
    ):
        from ansible_base.feature_flags.utils import create_initial_data

        flag_def = {
            'name': 'NEW_FLAG',
            'condition': 'some.condition',
            'ui_name': 'New Flag',
            'support_level': 'tech_preview',
            'visibility': 'public',
            # No 'value' here, expecting it from settings
        }
        mock_feature_flags_list.return_value = [flag_def]
        # --- Mocks for database interaction (for load_feature_flags part) ---
        mock_filter_queryset = MagicMock()
        # Simulate flag does NOT exist:
        mock_filter_queryset.first.return_value = None  # Crucial: .first() should return None
        mock_filter_queryset.exists.return_value = False  # If your code uses .exists()
        # Crucial: The queryset itself should be falsy if evaluated in a boolean context (e.g. if queryset:)
        # The error log showed a call to .__bool__(), so this is necessary.
        mock_filter_queryset.__bool__ = lambda self: False

        mock_aap_flag_model_cls.objects.filter.return_value = mock_filter_queryset

        mock_settings.set_attr('NEW_FLAG', True)

        mock_constructed_instance = MockAAPFlagInstance(
            name=flag_def['name'],  # Initialize with expected attributes for robustness
            condition=flag_def['condition'],
            # You can add other relevant fields from flag_def if needed by your code before save
        )
        mock_aap_flag_model_cls.side_effect = [mock_constructed_instance]

        mock_aap_flag_model_cls.objects.all.return_value = []

        # --- Call the function under test ---
        create_initial_data()

        # --- Assertions ---
        # Assert that Model.objects.filter was called correctly to check for existence
        mock_aap_flag_model_cls.objects.filter.assert_called_with(name='NEW_FLAG', condition='some.condition')

        # Assert that the model class was called (instantiated) with the correct arguments
        expected_constructor_args = {
            'name': 'NEW_FLAG',
            'condition': 'some.condition',
            'ui_name': 'New Flag',
            'support_level': 'tech_preview',
            'visibility': 'public',
            'value': True,  # Crucially, this should now be True from settings
        }
        mock_aap_flag_model_cls.assert_called_once_with(**expected_constructor_args)

        # Assert that methods were called on the *instance* returned by the constructor
        mock_constructed_instance.full_clean.assert_called_once()
        mock_constructed_instance.save.assert_called_once()

    @pytest.mark.django_db
    def test_load_feature_flags_creates_new_flag_with_default_value_if_not_in_settings(
        self, mock_apps_get_model, mock_aap_flag_model_cls, mock_settings, mock_logger, mock_feature_flags_list, mocker
    ):
        from ansible_base.feature_flags.utils import create_initial_data

        flag_def = {
            'name': 'NEW_FLAG_DEF_VAL',
            'condition': 'another.condition',
            'ui_name': 'New Flag Def Val',
            'support_level': 'supported',
            'visibility': 'private',
            'value': False,  # Default value in definition
        }
        mock_feature_flags_list.return_value = [flag_def]

        mock_empty_queryset = MagicMock()
        mock_empty_queryset.first.return_value = None
        mock_empty_queryset.__bool__ = lambda self: False
        mock_aap_flag_model_cls.objects.filter.return_value = mock_empty_queryset

        mock_constructed_flag = MockAAPFlagInstance()
        mock_aap_flag_model_cls.side_effect = [mock_constructed_flag]

        mock_aap_flag_model_cls.objects.all.return_value = []  # For purge_feature_flags

        create_initial_data()

        mock_aap_flag_model_cls.objects.filter.assert_called_with(name='NEW_FLAG_DEF_VAL', condition='another.condition')
        mock_aap_flag_model_cls.assert_called_once_with(**flag_def)  # value comes from flag_def

        mock_constructed_flag.full_clean.assert_called_once()
        mock_constructed_flag.save.assert_called_once()

    @pytest.mark.django_db
    def test_load_feature_flags_updates_existing_flag(
        self, mock_apps_get_model, mock_aap_flag_model_cls, mock_settings, mock_logger, mock_feature_flags_list, mocker
    ):
        from ansible_base.feature_flags.utils import create_initial_data

        flag_def_updated = {
            'name': 'EXISTING_FLAG',
            'condition': 'cond1',
            'ui_name': 'Updated UI Name',
            'support_level': 'beta',
            'visibility': 'internal',
            'support_url': 'new.url',
            'required': True,
            'toggle_type': 'static',
            'labels': ['new'],
            'description': 'new desc',
        }
        mock_feature_flags_list.return_value = [flag_def_updated]

        existing_db_flag = MockAAPFlagInstance(
            name='EXISTING_FLAG',
            condition='cond1',
            ui_name='Old UI Name',
            support_level='alpha',
            visibility='public',
            support_url='old.url',
            required=False,
            toggle_type='run-time',
            labels=['old'],
            description='old desc',
        )

        mock_existing_queryset = MagicMock()
        mock_existing_queryset.first.return_value = existing_db_flag
        mock_existing_queryset.__bool__ = lambda self: True
        mock_aap_flag_model_cls.objects.filter.return_value = mock_existing_queryset

        mock_aap_flag_model_cls.objects.all.return_value = [existing_db_flag]

        create_initial_data()

        mock_aap_flag_model_cls.objects.filter.assert_called_with(name='EXISTING_FLAG', condition='cond1')

        # Assert that the existing_db_flag instance was updated
        assert existing_db_flag.ui_name == 'Updated UI Name'
        assert existing_db_flag.support_level == 'beta'
        assert existing_db_flag.visibility == 'internal'
        assert existing_db_flag.support_url == 'new.url'
        assert existing_db_flag.required is True
        assert existing_db_flag.toggle_type == 'static'
        assert existing_db_flag.labels == ['new']
        assert existing_db_flag.description == 'new desc'

        existing_db_flag.full_clean.assert_called_once()
        existing_db_flag.save.assert_called_once()
        mock_aap_flag_model_cls.assert_not_called()  # No new instance created

    @pytest.mark.django_db
    def test_load_feature_flags_handles_specific_validation_error(
        self, mock_apps_get_model, mock_aap_flag_model_cls, mock_settings, mock_logger, mock_feature_flags_list, mocker
    ):
        from ansible_base.feature_flags.utils import create_initial_data

        flag_def = {'name': 'ERROR_FLAG', 'condition': 'err_cond', 'ui_name': 'Error Flag'}
        mock_feature_flags_list.return_value = [flag_def]

        mock_empty_queryset = MagicMock()
        mock_empty_queryset.first.return_value = None
        mock_empty_queryset.__bool__ = lambda self: False
        mock_aap_flag_model_cls.objects.filter.return_value = mock_empty_queryset

        mock_created_instance = MockAAPFlagInstance(**flag_def)
        validation_error = ValidationError('Aap flag with this Name and Condition already exists.')
        mock_created_instance.save.side_effect = validation_error

        mock_aap_flag_model_cls.side_effect = [mock_created_instance]

        mock_aap_flag_model_cls.objects.all.return_value = []

        create_initial_data()

        mock_logger.info.assert_called_once_with("Feature flag: ERROR_FLAG already exists")
        mock_logger.error.assert_not_called()
        mock_created_instance.full_clean.assert_called_once()

    @pytest.mark.django_db
    def test_load_feature_flags_logs_other_validation_errors(
        self, mock_apps_get_model, mock_aap_flag_model_cls, mock_settings, mock_logger, mock_feature_flags_list, mocker
    ):
        from ansible_base.feature_flags.utils import create_initial_data

        flag_def = {'name': 'OTHER_ERROR_FLAG', 'condition': 'other_err_cond', 'ui_name': 'Other Error'}
        mock_feature_flags_list.return_value = [flag_def]

        mock_empty_queryset = MagicMock()
        mock_empty_queryset.first.return_value = None
        mock_empty_queryset.__bool__ = lambda self: False
        mock_aap_flag_model_cls.objects.filter.return_value = mock_empty_queryset

        mock_created_instance = MockAAPFlagInstance(**flag_def)
        validation_error = ValidationError('Some other validation error.')
        mock_created_instance.full_clean.side_effect = validation_error

        mock_aap_flag_model_cls.side_effect = [mock_created_instance]

        mock_aap_flag_model_cls.objects.all.return_value = []

        create_initial_data()

        mock_logger.error.assert_called_once_with(f"Invalid feature flag: {flag_def['name']}. Error: {validation_error}")
        mock_logger.info.assert_not_called()
        mock_created_instance.save.assert_not_called()

    @pytest.mark.django_db
    def test_purge_feature_flags_removes_obsolete_flag(self, mock_apps_get_model, mock_aap_flag_model_cls, mock_logger, mock_feature_flags_list):
        from ansible_base.feature_flags.utils import create_initial_data

        obsolete_flag_in_db = MockAAPFlagInstance(name='OBSOLETE_FLAG', condition='obs_cond')

        mock_aap_flag_model_cls.objects.all.return_value = [obsolete_flag_in_db]
        mock_empty_queryset = MagicMock()
        mock_empty_queryset.first.return_value = None
        mock_empty_queryset.__bool__ = lambda self: False
        mock_aap_flag_model_cls.objects.filter.return_value = mock_empty_queryset

        create_initial_data()

        mock_aap_flag_model_cls.objects.all.assert_called_once()
        obsolete_flag_in_db.delete.assert_called_once()
        mock_logger.info.assert_any_call(f"Deleting feature flag: {obsolete_flag_in_db.name} as it is no longer available as a platform flag")

    @pytest.mark.django_db
    def test_purge_feature_flags_keeps_current_flag(self, mock_apps_get_model, mock_aap_flag_model_cls, mock_logger, mock_feature_flags_list):
        from ansible_base.feature_flags.utils import create_initial_data

        current_flag_def = {'name': 'CURRENT_FLAG', 'condition': 'curr_cond', 'ui_name': 'Current'}
        mock_feature_flags_list.return_value = [current_flag_def]

        current_flag_in_db = MockAAPFlagInstance(name='CURRENT_FLAG', condition='curr_cond')

        mock_aap_flag_model_cls.objects.all.return_value = [current_flag_in_db]

        # For load_feature_flags part (update existing)
        mock_existing_queryset = MagicMock()
        mock_existing_queryset.first.return_value = current_flag_in_db
        mock_existing_queryset.__bool__ = lambda self: True
        mock_aap_flag_model_cls.objects.filter.return_value = mock_existing_queryset

        create_initial_data()

        current_flag_in_db.delete.assert_not_called()
        # Check that logger.info for deletion was not called for this flag
        for call_arg in mock_logger.info.call_args_list:
            assert "Deleting feature flag: CURRENT_FLAG" not in call_arg[0][0]

        current_flag_in_db.save.assert_called_once()

    def test_create_initial_data_call_order(self, mocker):
        from ansible_base.feature_flags.utils import create_initial_data

        # Mock the inner functions directly to check call order
        mock_delete = mocker.patch(f"{MODULE_PATH}.purge_feature_flags")
        mock_load = mocker.patch(f"{MODULE_PATH}.load_feature_flags")

        manager = MagicMock()
        manager.attach_mock(mock_delete, 'delete_flags')
        manager.attach_mock(mock_load, 'load_flags')

        create_initial_data()

        expected_calls = [call.delete_flags(), call.load_flags()]
        assert manager.mock_calls == expected_calls
