from ansible_base.lib.abstract_models.common import AbstractCommonModel, CreatableModel


class ImmutableCommonModel(AbstractCommonModel, CreatableModel):
    """
    A save-once (immutable) base model.
    Functionally similar to CommonModel, but does not allow modification of the object after creation
    and does not include the modified/modifed_by fields.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError(f"{self.__class__.__name__} is immutable and cannot be modified.")

        return super().save(*args, **kwargs)
