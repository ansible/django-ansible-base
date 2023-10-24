LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '%(asctime)s %(levelname)-8s %(name)s %(message)s'},
    },
    'handlers': {
        'console': {
            '()': 'logging.StreamHandler',
            'level': 'DEBUG',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'ansible_base': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}

