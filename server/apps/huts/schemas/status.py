
from enum import Enum


class CreateOrUpdateStatus(str, Enum):
    updated = 'updated'
    created = 'created'
    deleted = 'deleted'
    ignored = 'ignored'
    exists  = 'exists'