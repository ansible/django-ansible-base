"""
Variables defined in this file will override the settings from defaults.py
to merge back to existing settings, use the following dynaconf pattern:

# Dunder merging
EXISTING_STRUCTURE__NESTED_KEY = value
EXISTING_STRUCTURE__NESTED_KEY__NESTED_KEY = value

# Merge Marker as @token
EXISTING_STRUCTURE = "@merge key=value"
EXISTING_STRUCTURE = '@merge {"key": "value"}'
EXISTING_LIST = "@merge item1, item2, item3"
EXISTING_LIST = "@merge_unique item1"
EXISTING_LIST = "@insert 0 item"

# Merge marker as item
EXISTING_STRUCTURE = {
  "key": "value",
  "dynaconf_merge": True
}
EXISTING_LIST = ["item1", "dynaconf_merge"]
"""

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "db.sqlite3",
    }
}
