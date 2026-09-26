"""DOT validator extension: injects the provider's claim shapes.

django-oauth-toolkit calls ``get_additional_claims`` when building ID tokens,
userinfo responses and JWT access tokens (``get_jwt_bearer_token``). We add
the shared claim set from ``tokens.claims_for_user`` so every token surface
carries the same roles claims (legacy Zitadel-shaped map + plain ``roles``
list), built from Django groups.
"""

from typing import Any

from oauth2_provider.oauth2_validators import OAuth2Validator

from django.conf import settings

from . import tokens


class ProviderOAuth2Validator(OAuth2Validator):
    # Return all claims regardless of granted scopes — matches the legacy
    # provider behavior the frontend relies on (roles on every token).
    oidc_claim_scope = None  # type: ignore[assignment]

    def get_additional_claims(self, request: Any) -> dict[str, Any]:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return {}
        claims = tokens.claims_for_user(user)
        # ``sub`` is mandatory in OIDC; DOT defaults to the user pk.
        claims["sub"] = str(user.pk)
        project = getattr(settings, "ZITADEL_PROJECT", "")
        if not project:
            # ``sub`` already included above; nothing else required.
            pass
        return claims
