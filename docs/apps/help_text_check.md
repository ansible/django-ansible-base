# Help Text Checker

A simple application to provide a management command which can inspect django models to see if all fields have help_text related to them.

## Settings

Add `ansible_base.help_text_check` to your installed apps:

```
INSTALLED_APPS = [
    ...
    'ansible_base.help_text_check',
]
```

### Additional Settings

There are no additional settings required.

## URLS

This feature does not require any URLs.

## Using the management command

The management command can be run on its own as:

```
manage.py help_text_check
```

By default this will report on all models the ORM knows about.

### Restricting which applications are searched

If you would like to restrict which models will be queried you can do so on a per-application basis by passing in a comma separated value like:

```
manage.py help_text_check --applications=<application1>,<application2>,...
```

Note, each entry in the passed applications is compared to the installed applications and if an installed application name contains an entry specified in applications it will be added to the list of applications to check.

For example, DAB has a number of applications. These can all be tested with the following:

```
manage.py help_text_check --applications=dab
```

This is because the name of all applications in DAB start with `dab_`. If you only wanted to test a single application in DAB you do that like:

```
manage.py help_text_check --application=dab_authentication
```

### Ignoring specific fields

If there are specific fields you want to ignore on a model you can create an "ignore file" where each line in the file is in the syntax of:
```
application.model.field_name
```

Once the file is created you can pass that as the `--ignore-file` parameter like:
```
manage.py help_text_check --ignore-file=<path to file>
```

### Global ignore

The `id` field of all models is ignored by default

If you want to report on the globally ignored fields you can pass in `--skip-global-ignore`

### Return codes

This script returns 3 possible return codes
0 - everything is fine
1 - One or more field is missing help_text
255 - The ignore file was unable to be read for some reason (see output)
