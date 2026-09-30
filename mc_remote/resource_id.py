"""Input resource IDs retain the namespace omission allowed by wire §5.0.2."""

import re

_RESOURCE_ID = re.compile(r"(?:[a-z0-9_.-]+:)?[a-z0-9/._-]+")


def resource_id(value, context):
    if not isinstance(value, str) or _RESOURCE_ID.fullmatch(value) is None:
        raise ValueError(f"{context} must be a resource ID (with or without namespace)")
    return value
