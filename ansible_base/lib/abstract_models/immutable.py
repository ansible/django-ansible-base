#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from django.db import models


class ImmutableModel(models.Model):
    """
    A save-once (immutable) base model. Simply blocks any save attempts after the first.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError(f"{self.__class__.__name__} is immutable and cannot be modified.")

        return super().save(*args, **kwargs)
