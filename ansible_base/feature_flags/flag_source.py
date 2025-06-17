from django.apps import apps
from flags.sources import Condition


class DatabaseCondition(Condition):
    """Condition that includes the AAPFlags database object
    This is required to ensure that enable_flag/disable_flag calls
    can work as expected, with the custom flag objects
    """

    def __init__(self, condition, value, required=False, obj=None):
        super().__init__(condition, value, required=required)
        self.obj = obj


class AAPFlagSource(object):
    """The customer AAP flag source, retrieves a list of all flags in the database"""

    def get_queryset(self):
        aap_flags = apps.get_model('dab_feature_flags', 'AAPFlag')
        return aap_flags.objects.all()

    def get_flags(self):
        flags = {}
        for o in self.get_queryset():
            if o.name not in flags:
                flags[o.name] = []
            flags[o.name].append(DatabaseCondition(o.condition, o.value, required=o.required, obj=o))
        return flags
