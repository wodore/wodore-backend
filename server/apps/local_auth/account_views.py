"""Self-service account overview (spec: account-management).

allauth ships flows (password, MFA, sessions, email) but no single landing
page. This view gives every signed-in user one place showing their account
and linking to the management pages - no admin access needed.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


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
