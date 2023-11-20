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
