"""Self-service account overview and login redirects for the built-in
account system (spec: account-management).

allauth ships flows (password, MFA, sessions, email) but no single landing
page. ``account_overview`` gives every signed-in user one place showing
their account and linking to the management pages - no admin access
needed. ``admin_login_redirect`` bridges the Django admin's login to the
active provider's login surface while preserving the original target
(the admin sends ``/admin/login/?next=<deep link>``).
"""

from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render


def _safe_next(value: str | None) -> str | None:
    """Relative targets only (no open redirects)."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return None


def admin_login_redirect(request, login_path: str = "/accounts/login/"):
    """Forward the admin's login redirect, preserving the deep-link target.

    The Django admin redirects unauthenticated deep links to
    ``/admin/login/?next=<original path>``. This view hands the user to the
    active provider's login (allauth or the Zitadel RP) carrying that
    ``next`` along, so the original page is reached after signing in.
    """
    target = _safe_next(request.GET.get("next")) or "/admin/"
    separator = "&" if "?" in login_path else "?"
    return HttpResponseRedirect(f"{login_path}{separator}next={quote(target)}")


@login_required
def account_overview(request):
    from allauth.mfa.models import Authenticator

    mfa_types = list(
        Authenticator.objects.filter(user=request.user).values_list("type", flat=True)
    )
    return render(
        request,
        "local_auth/account_overview.html",
        {
            "account_user": request.user,
            "mfa_types": mfa_types,
        },
    )
