def unique_fields_for_model(ModelCls, include_pk=False, flatten_unique_together=True):
    """
    Given a model class, determine the names of the unique fields.

    If `include_pk` is True, the primary key field will be included in the set of unique fields.

    If `flatten_unique_together` is True, the unique_together fields will be flattened into the set
    of unique fields (otherwise their tuples will be included).
    """

    unique_fields = set()

    # First the concrete fields
    for field in ModelCls._meta.fields:
        if field.unique and (include_pk or (field != ModelCls._meta.pk)):
            unique_fields.add(field.name)

    # But now the unique_together fields
    for unique_together in ModelCls._meta.unique_together:
        if flatten_unique_together:
            for field in unique_together:
                if include_pk or (field != ModelCls._meta.pk):
                    unique_fields.add(field)
        else:
            unique_fields.add(unique_together)

    return unique_fields
