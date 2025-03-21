from django.apps import apps
from flags.sources import Condition


class DatabaseCondition(Condition):
    """Condition that includes the FlagState database object"""

    def __init__(self, condition, value, required=False, obj=None):
        super().__init__(condition, value, required=required)
        self.obj = obj


class AAPFlagSource(object):

    def get_queryset(self):
        FlagState = apps.get_model('dab_feature_flags', 'AAPFlag')
        return FlagState.objects.all()

    def get_flags(self):
        flags = {}
        for o in self.get_queryset():
            if o.name not in flags:
                flags[o.name] = []
            flags[o.name].append(DatabaseCondition(o.condition, o.value, required=o.required, obj=o))
        return flags
