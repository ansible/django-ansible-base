from django.apps import AppConfig


class HelpTextCheckConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.help_text_check'
    label = 'dab_help_text_check'
    verbose_name = 'Django Model Help Text Checker'
