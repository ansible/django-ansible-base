# Management commands

django-ansible-base includes built in management commands.

# ansible_base.authentication.management.commands.authenticators

This command provide a CLI interface into authenticators. It includes listing/enabling and disabling and adding a default local authentication along with a built in admin/password user. Building of the default local authenticator and user needs to be done if you have removed the default Model login and are instead using the local authenticator class (see authentication.md)
