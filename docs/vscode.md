## Overview

Configure VSCode to allow developers to use the built-in vscode debugging tool for test_app.

### Prerequisites

1. create a `.env` file in django-ansible-base folder with the following content,

```python
DJANGO_SETTINGS_MODULE=test_app.sqlite3settings
```

2. Copy the tools/vscode/ contents into .vscode/ in your django-ansible-base folder

Now you should be able to run the test_app server in debug mode via VSCode

3. Restart VSCode so that it detects the new launch configuration

### Launch the debugger

Click the Run and Debug tab in VSCode and click the drop down to select `Test App Server` and click green triangle to run it

Set a debug point in the code and it should trigger

Sometimes it is useful to play around in shell_plus environment. Launch the a shell_plus process by selecting `Test App Shell Plus`. You can start this while the `Test App Server` is running.

### Running Tests

the `settings.json` test file allows you to run a test via VSCode.

Click the Testing icon and navigate to the test you wish to run. Click either Run or Debug test.


### Resetting database

Delete the `django-ansible-base/db.sqlite3` file and re-run the server to get a fresh database.
