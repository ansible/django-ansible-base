# Redis Client

django-ansible-base offers a redis client which allows for single/clustered nodes as well as with or without TLS.

To leverage this client you can setup your Django cache like:
```
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            # Note, the location is not really used but we parse it in the client to get settings like host/port/username/etc.
            "LOCATION": f"redis://{os.environ.get('REDIS_USER')}:{os.environ.get('REDIS_PASS')}@{os.environ.get('REDIS_HOST')}:{os.environ.get('REDIS_PORT')}",
            "KEY_PREFIX": '<service name>',
            "OPTIONS": {
                "CLIENT_CLASS": "ansible_base.lib.redis.RedisClient",
                "CLIENT_CLASS_KWARGS": {
                    "clustered": to_python_boolean(os.environ.get('REDIS_IS_CLUSTERED', False)),
                    'clustered_hosts': "<host 1>:<port>,<host 2>:<port>,[...],<host N>:<port>",
                    'ssl': to_python_boolean(os.environ.get('REDIS_TLS', True)),
                    'ssl_keyfile': '/etc/path/redis.key',
                    'ssl_certfile': '/etc/path/redis.cert',
                    'ssl_cert_reqs': 'required',
                    'ssl_ca_certs': '/etc/path/redis_ca.cert',
                    'ssl_check_hostname': False,
                },
            },
        }
    }
```

As noted, the LOCATION field is required but not used directly for the connection. Instead the URL is parsed and fields like host, port, user, pass is extracted and added as connection parameters. These fields from the URL will override OPTIONS fields.

The `KEY_PREFIX` is useful if you are sharing a redis instance with multiple services. This will automatically append the `<prefix>:` to any key name.

Inside the `OPTIONS` are two fields which indicate whether we are connecting to a cluster or not.

The first one is `clustered` which will tell the client to use the RedisCluster instead of just Redis.

The second option is `clustered_hosts`. If unset, we will simply connect to the server specified in `LOCATION` will be contacted and user. However, if that node is down or unreachable, the cache will fail. If you set `clustered_hosts` as long as any node can be contacted and will share a healthy cluster info, the cache can be started.

The remaining fields in the example above control the TLS settings for connecting to Redis. These fields are documented in the redis_py documentation. 

Any additional fields set in the `OPTIONS` will be sent directly to the Redis client. 
