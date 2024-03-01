# django-ansible-base tests

We try to maintain at least an 80% test coverage of django-ansible-base. This is enforced through GitHub actions on PR creation. The GitHub actions use SonarCloud to scan the code for issus one of which is code coverage.

All tests for django-ansible-base are located in `test_app/tests`. The directory structure in that folder mimics that of ansible_base so you can easily tell which test files cover which files in ansible_base.

## Running tests

To run the test suite locally you can use tox. By default, with no arguments, tox will attempt to run the tests in various version of python. To run a specific version you can add the `-e` parameter like:
```
tox -e 311
```

### Test database

Tests require PostgreSQL running in order to pass.
Running PostgreSQL can be done by running `make postgres` in the root of your django-ansible-base clone.
This will create a detached/daemonized PostgreSQL container called `dab_postgres`.

If all goes according to plan, tox should automatically kill the container after the tests run.
However, if you stop tox early or otherwise need to manually kill the container, you can run `make stop-postgres`.

## Checking code coverage locally

Tox will also create code coverage reports when run. These can be found in various places. For example, git ignored, `coverage.xml` and `coverage.json` will be crated in the root folders. For human consumption you will also see an `htmlcov` folder in which is an index.html file. If you open this file in a browser you will be presented with a coverage report. If you change the tests, run again and reload the file the report should be updated.


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

brew install $USER/local/libxmlsec1@1.2.37
tox -e 311

unset HOMEBREW_NO_INSTALL_FROM_API
brew untap homebrew/core
```
