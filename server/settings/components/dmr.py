"""
django-modern-rest (dmr) settings.

``WodoreSerializer`` (``server.apps.api.serializer``) keeps the wire
contract of the former django-ninja setup: responses are JSON with
``by_alias`` and **exclude_unset** semantics (fields not set during
validation are not emitted), matching ninja's ``exclude_unset=True``
router behaviour.

Response validation stays ON in development and test; production turns
it off below — the contract is enforced by tests, snapshots and CI
instead of paying the runtime cost per request.
"""

from os import environ

from dmr.settings import Settings

DMR_SETTINGS = {
    Settings.semantic_responses: True,
}

if environ.get("DJANGO_ENV") == "production":
    DMR_SETTINGS[Settings.validate_responses] = False
