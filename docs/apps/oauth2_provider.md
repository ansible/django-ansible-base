# Differences from AWX

* Because of how DAB's router works, we don't allow for POSTing to (for example)
  `/applications/PK/tokens/` to create a token which belongs to an application.
  The workaround is to just use /tokens/ and in the body specify
  `{"application": PK}`.
