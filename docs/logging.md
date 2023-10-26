# Logging

Django-ansible-base uses pythons logging library to emit messages as needed. If you would like to control the messages coming out of django-ansible-base you can add a logger for `ansible_base` like:
```
        'ansible_base': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
```

