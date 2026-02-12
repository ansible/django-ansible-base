# django-ansible-base tests

We try to maintain at least an 80% test coverage of django-ansible-base. This is enforced through GitHub actions on PR creation. The GitHub actions use SonarCloud to scan the code for issus one of which is code coverage.

All tests for django-ansible-base are located in `test_app/tests`. The directory structure in that folder mimics that of ansible_base so you can easily tell which test files cover which files in ansible_base.

## Running tests

### Requirements
Ensure you have the needed python dependencies installed (either in your system or a virtual env):
```
pip install -r requirements/requirements_dev.txt
```

### Run
To run the test suite locally you can use nox. By default, with no arguments, nox will run all sessions. To run a specific session you can use the `-s` parameter like:
```
nox -s py312
```

Available test sessions (for each of 3.11 and 3.12):
- `py311` / `py312` - Main test suite
- `py311-check` / `py312-check` - Django system checks and migration verification
- `py311-sqlite` / `py312-sqlite` - Test suite with SQLite backend
- `py311-django4` / `py312-django4` - Test suite pinned to Django 4.2
- `py311-in-files` / `py312-in-files` - Test suite using individual `.in` requirement files

Available lint/utility sessions:
- `flake8` - Flake8 linter
- `black` - Black code formatter
- `isort` - isort import sorter
- `lint` - Run all linters at once
- `stop_db` - Stop the test PostgreSQL container

You can list all available sessions with:
```
nox -l
```

### Test database

Tests require PostgreSQL running in order to pass.

nox will automatically create a fresh PostgreSQL container (`dab-test-postgres`) before running tests and destroy it when the session finishes. This ensures a clean database state for every run.

## Checking code coverage locally

nox will also create code coverage reports when run. These can be found in various places. For example, git ignored, `coverage.xml` and `coverage.json` will be crated in the root folders. For human consumption you will also see an `htmlcov` folder in which is an index.html file. If you open this file in a browser you will be presented with a coverage report. If you change the tests, run again and reload the file the report should be updated.


# OS X SAML python library issue
With the SAML adapter we need to include python xmlsec library.
On Mac this can be a bit of a problem because brew wants to use the latest libxmlsec1 library but the python package has not been updated to take advantage of it.

The instructions on https://stackoverflow.com/questions/76005401/cant-install-xmlsec-via-pip help to install an olderversion of libxmlsec1.
There was also a second step I needed to perform according to https://github.com/Homebrew/homebrew-core/issues/135418#issuecomment-1614946043

In the end the steps I needed to perform were:
```
brew tap-new $USER/local
export HOMEBREW_NO_INSTALL_FROM_API=1
brew tap homebrew/core
brew extract --version=1.2.37 libxmlsec1 $USER/local
brew uninstall libxmlsec1
export EDITOR=vi
brew edit $USER/local/libxmlsec1@1.2.37
	Change the url=" line to be:
        url "https://www.aleksey.com/xmlsec/download/older-releases/xmlsec1-1.2.37.tar.gz"
	Change any occurrences of "openssl@1.1" to "openssl@3"

brew install $USER/local/libxmlsec1@1.2.37
nox -s py311

unset HOMEBREW_NO_INSTALL_FROM_API
brew untap homebrew/core
```
