## Cached Dynamic Timeout Session Store

This is a session store which is a child class of the `cached_db` session store. 

It does exactly the same thing but calls `get_preference('SESSION_COOKE_AGE')` to determine how long to allow the sessions to remain valid.

To take advantage of this, add this setting:
```
SESSION_ENGINE = "ansible_base.lib.sessions.stores.cached_dynamic_timeout"
```

Make sure you have a default setting for `SESSION_COOKIE_AGE` like:
```
# Seconds before sessions expire.
# Note: This setting may be overridden by database settings.
SESSION_COOKIE_AGE = 1800
```

And then make sure that your `get_preference` function can dynamically return a value for `SESSION_COOKIE_AGE`.

After changing this value in the system new sessions cut with it will expire based on the setting.
