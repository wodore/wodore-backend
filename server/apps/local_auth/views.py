"""Views for the local dev/test OIDC provider (spec: local-auth-provider).

Endpoints (mounted under ``/oauth/local/``):

- ``GET /.well-known/openid-configuration`` - discovery
- ``GET/POST /authorize`` - authorization-code flow with PKCE (S256); renders
  a minimal login form when unauthenticated; ``prompt=none`` answers with an
  immediate redirect (silent renew) or ``error=login_required``
- ``POST /token`` - ``authorization_code`` (PKCE) and dev/test ``password``
  grants; issues RS256 access/ID tokens
- ``GET /userinfo`` - requires the access token; Zitadel-shaped role claims
- ``GET /jwks`` - public key for the local dev keypair
- ``GET /end_session`` - clears the Django session

Dev/test-only by construction (see the app docstring) - nothing here is
hardened for production exposure.
"""

import base64
import hashlib
import hmac
import logging
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import tokens

logger = logging.getLogger(__name__)

_AUTHORIZATION_CODE_TTL = 60  # seconds
_PRESERVED_PARAMS = (
    "client_id",
    "redirect_uri",
    "response_type",
    "scope",
    "state",
    "nonce",
    "code_challenge",
    "code_challenge_method",
    "prompt",
)


def _issuer(request: HttpRequest) -> str:
    return request.build_absolute_uri("/oauth/local").rstrip("/")


def _is_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _redirect_with(redirect_uri: str, **params: str) -> HttpResponse:
    separator = "&" if "?" in redirect_uri else "?"
    query = urlencode({k: v for k, v in params.items() if v})
    return HttpResponse(
        status=302, headers={"Location": f"{redirect_uri}{separator}{query}"}
    )


def _validate_authorize_request(
    request: HttpRequest,
) -> tuple[dict[str, str], HttpResponse | None]:
    """Return (params, None) when valid, or (params, error_response)."""
    params = {name: request.GET.get(name, "") for name in _PRESERVED_PARAMS}
    redirect_uri = params["redirect_uri"]

    if not _is_http_url(redirect_uri):
        return params, JsonResponse(
            {
                "error": "invalid_request",
                "error_description": "redirect_uri must be an absolute http(s) URL",
            },
            status=400,
        )
    if params["response_type"] != "code":
        return params, _redirect_with(
            redirect_uri, error="unsupported_response_type", state=params["state"]
        )
    if params["client_id"] != settings.LOCAL_AUTH_CLIENT_ID:
        return params, _redirect_with(
            redirect_uri, error="unauthorized_client", state=params["state"]
        )
    method = params["code_challenge_method"] or "S256"
    if not params["code_challenge"] or method != "S256":
        return params, _redirect_with(
            redirect_uri,
            error="invalid_request",
            state=params["state"],
            error_description="PKCE with code_challenge_method=S256 is required",
        )
    return params, None


def _store_authorization_code(params: dict[str, str], user_id: int) -> str:
    from django.core.cache import cache

    code = secrets.token_urlsafe(32)
    cache.set(
        f"local_auth:code:{code}",
        {
            "user_id": user_id,
            "challenge": params["code_challenge"],
            "client_id": params["client_id"],
            "redirect_uri": params["redirect_uri"],
            "nonce": params["nonce"],
        },
        timeout=_AUTHORIZATION_CODE_TTL,
    )
    return code


@require_GET
def discovery(request: HttpRequest) -> JsonResponse:
    issuer = _issuer(request)
    return JsonResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "userinfo_endpoint": f"{issuer}/userinfo",
            "jwks_uri": f"{issuer}/jwks",
            "end_session_endpoint": f"{issuer}/end_session",
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "prompt_values_supported": ["none"],
            "grant_types_supported": ["authorization_code", "password"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }
    )


def authorize(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        return _authorize_post(request)
    return _authorize_get(request)


def _authorize_get(request: HttpRequest) -> HttpResponse:
    params, error = _validate_authorize_request(request)
    redirect_uri = params["redirect_uri"]
    if error is not None:
        return error

    user_pk = request.user.pk if request.user.is_authenticated else None
    if params.get("prompt") == "none" or user_pk is not None:
        if user_pk is not None:
            code = _store_authorization_code(params, user_pk)
            return _redirect_with(redirect_uri, code=code, state=params["state"])
        # prompt=none without a session: silent renew must learn this without
        # triggering an interactive login.
        return _redirect_with(
            redirect_uri, error="login_required", state=params["state"]
        )
    return render(request, "local_auth/login.html", {"params": params})


def _authorize_post(request: HttpRequest) -> HttpResponse:
    params = {name: request.POST.get(name, "") for name in _PRESERVED_PARAMS}
    redirect_uri = params["redirect_uri"]
    if not _is_http_url(redirect_uri):
        return JsonResponse(
            {
                "error": "invalid_request",
                "error_description": "redirect_uri must be an absolute http(s) URL",
            },
            status=400,
        )

    user = authenticate(
        request,
        username=request.POST.get("username", ""),
        password=request.POST.get("password", ""),
    )
    if user is None:
        logger.warning(
            "local_auth: failed login for %r", request.POST.get("username", "")
        )
        return render(
            request,
            "local_auth/login.html",
            {"params": params, "error": "Invalid credentials."},
            status=401,
        )
    login(request, user)
    code = _store_authorization_code(params, user.pk)
    return _redirect_with(redirect_uri, code=code, state=params["state"])


def _verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(computed, challenge)


@require_POST
@csrf_exempt  # OAuth2 token endpoints are machine-to-machine; no CSRF token
def token(request: HttpRequest) -> JsonResponse:
    grant_type = request.POST.get("grant_type", "")
    if grant_type == "authorization_code":
        return _token_authorization_code(request)
    if grant_type == "password":
        return _token_password(request)
    return JsonResponse(
        {
            "error": "unsupported_grant_type",
            "error_description": f"grant_type '{grant_type}' is not supported",
        },
        status=400,
    )


def _token_authorization_code(request: HttpRequest) -> JsonResponse:
    from django.core.cache import cache

    code = request.POST.get("code", "")
    record = cache.get(f"local_auth:code:{code}")
    cache.delete(f"local_auth:code:{code}")  # single use, always
    if not isinstance(record, dict):
        return _invalid_grant("unknown or expired code")

    if request.POST.get("redirect_uri", "") != record["redirect_uri"]:
        return _invalid_grant("redirect_uri mismatch")
    if request.POST.get("client_id", "") != record["client_id"]:
        return _invalid_grant("client_id mismatch")
    verifier = request.POST.get("code_verifier", "")
    if not verifier or not _verify_pkce(verifier, record["challenge"]):
        return _invalid_grant("PKCE verification failed")

    from django.contrib.auth.models import User

    try:
        user = User.objects.get(pk=record["user_id"], is_active=True)
    except User.DoesNotExist:
        return _invalid_grant("user no longer exists")

    return _token_response(
        user, _issuer(request), record["client_id"], record.get("nonce", "")
    )


def _token_password(request: HttpRequest) -> JsonResponse:
    user = authenticate(
        request,
        username=request.POST.get("username", ""),
        password=request.POST.get("password", ""),
    )
    if user is None:
        return JsonResponse(
            {"error": "invalid_grant", "error_description": "invalid credentials"},
            status=400,
        )
    return _token_response(user, _issuer(request), settings.LOCAL_AUTH_CLIENT_ID, "")


def _token_response(user, issuer: str, client_id: str, nonce: str) -> JsonResponse:
    access_token = tokens.issue_access_token(user, issuer, client_id)
    id_token = tokens.issue_id_token(user, issuer, client_id, nonce=nonce)
    return JsonResponse(
        {
            "access_token": access_token,
            "id_token": id_token,
            "token_type": "Bearer",
            "expires_in": tokens.ACCESS_TOKEN_LIFETIME,
        }
    )


def _invalid_grant(description: str) -> JsonResponse:
    return JsonResponse(
        {"error": "invalid_grant", "error_description": description}, status=400
    )


@require_GET
def userinfo(request: HttpRequest) -> JsonResponse | HttpResponse:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return JsonResponse(
            {"error": "invalid_token", "error_description": "Bearer token required"},
            status=401,
        )
    try:
        claims = tokens.verify_access_token(header.removeprefix("Bearer "))
    except ValueError:
        return JsonResponse(
            {
                "error": "invalid_token",
                "error_description": "token is invalid or expired",
            },
            status=401,
        )

    from django.contrib.auth.models import User

    try:
        user = User.objects.get(pk=claims["sub"], is_active=True)
    except (User.DoesNotExist, KeyError, ValueError):
        return JsonResponse(
            {"error": "invalid_token", "error_description": "unknown subject"},
            status=401,
        )
    return JsonResponse(_userinfo_claims(user))


def _userinfo_claims(user) -> dict[str, object]:
    claims: dict[str, object] = {
        "sub": str(user.pk),
        "email": user.email,
        "name": user.get_full_name() or user.username,
        "picture": tokens.gravatar_url(user.email),
        # The claim the frontend store reads; values are unused (keys only).
        "urn:zitadel:iam:org:project:roles": tokens.roles_claim(user),
    }
    return claims


@require_GET
def jwks(request: HttpRequest) -> JsonResponse:
    public = tokens.get_public_jwk()
    return JsonResponse({"keys": [{k: v for k, v in public.items()}]})


@require_GET
def end_session(request: HttpRequest) -> HttpResponse:
    logout(request)
    target = request.GET.get("post_logout_redirect_uri", "/")
    if not _is_http_url(target):
        target = "/"
    return HttpResponse(status=302, headers={"Location": target})
