from django.apps import apps
from flags.sources import Condition


class AAPFlagSource(object):

    def get_queryset(self):
        aap_flags = apps.get_model('dab_feature_flags', 'AAPFlag')
        return aap_flags.objects.all()

    def get_flags(self):
        flags = {}
        for o in self.get_queryset():
            if o.name not in flags:
                flags[o.name] = []
            flags[o.name].append(Condition(o.condition, o.value, required=o.required))
        return flags
