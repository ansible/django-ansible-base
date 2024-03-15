class ImmutableModel:
    # In case the model is extending CommonModel.
    modified = None
    modified_by = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # MRO dictates that we must be first.
        if cls.__bases__[0] is not ImmutableModel:
            raise ValueError(f"ImmutableModel must be the first base class for {cls.__name__}")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError(f"{self.__class__.__name__} is immutable and cannot be modified.")

        return super().save(*args, **kwargs)

    def __getattribute__(self, name):
        # This is a bit of a hack, there is no good way to remove these fields, because they exist up the chain
        # if the model inherits from CommonModel.
        if name in ('modified', 'modified_by'):
            raise AttributeError(f"{self.__class__.__name__} has no attribute {name}")

        return super().__getattribute__(name)
