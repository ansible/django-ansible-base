from ansible_base.rest_filters.rest_framework.field_lookup_backend import FieldLookupBackend


class ActivityStreamFilterBackend(FieldLookupBackend):
    TREAT_JSONFIELD_AS_TEXT = False
