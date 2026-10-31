"""Open-in action registry API (OpenSpec ``external-actions``).

Three endpoints over :class:`ExternalAction` — a thin scoping row on
:class:`ExternalLink` (D1; the link owns the URL template, i18n label
and health checks):

* ``GET /v1/links/actions?kind=&iso=&lang=`` — public rows
  (``user IS NULL``), anonymous, CDN-cacheable. Cache key is the full
  query string: ``kind``, ``iso`` AND ``lang`` (labels are localized —
  the basemaps ``LanguageQuery`` pattern; without ``lang`` a CDN edge
  would serve the first responder's language to everyone).
* ``GET /v1/my/links/actions?kind=&iso=&lang=`` — the requester's rows
  only, via :class:`MyApiController` — the ``/v1/my/`` namespace's
  policy boundary (auth required + ``private, no-store`` + never CDN;
  D5).
* ``GET /v1/links/actions/{identifier}?<template vars>`` — server-side
  render for QR/e-mail contexts; ``{identifier}`` IS the backing
  ``ExternalLink.identifier`` (the action has none of its own, D6).
  Renders when a public action exists for the link OR the requester
  owns one; else 404.

Matching semantics (D2/D3): ``kind`` is the kind identifier (2-slug
``Category.identifier``, unique per design) — exact match against the
action's ``kinds``, or actions with empty ``kinds`` (any point).
``iso`` is ISO-3166 alpha-2, case-insensitive (normalized to
uppercase), matching membership or empty ``countries`` (global).
Omitted ``kind`` applies no kind filter; omitted ``iso`` none either.
"""

from __future__ import annotations

from datetime import date, timedelta
from http import HTTPStatus
from typing import Any, ClassVar, override

import pydantic
from dmr import APIError, Path, Query, modify
from dmr.routing import path

from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponseBase
from django.utils import timezone

from server.apps.api.auth import AuthBearer
from server.apps.api.controller import ApiController, raise_not_found
from server.apps.api.error_codes import ErrorCode
from server.apps.translations import LanguageQuery
from server.apps.translations import override as lang_override

from .models import ExternalAction, ExternalLink


class ActionsQuery(LanguageQuery):
    """Shared query params of the action list endpoints."""

    model_config = LanguageQuery.model_config

    kind: str | None = None
    iso: str | None = None


ActionsQuery.model_fields["kind"].description = (
    "Kind identifier (2-slug Category.identifier, e.g. 'map.transport'); "
    "omitted = no kind filter. Actions with empty kinds match any point."
)
ActionsQuery.model_fields["iso"].description = (
    "ISO-3166 alpha-2 country code (case-insensitive); omitted = no "
    "country filter. Actions with empty countries are global."
)


class RenderQuery(LanguageQuery):
    """Render endpoint params: any template variables pass through.

    ``lang`` localizes the rendered URL; every other query parameter is
    handed to ``ExternalLink.render_url`` as a template variable
    (unknown variables are ignored by ``str.format`` semantics).
    """

    model_config = pydantic.ConfigDict(extra="allow")


class RenderPath(pydantic.BaseModel):
    """Render endpoint path param: the backing link identifier."""

    identifier: str


def _action_rows(queryset: QuerySet[ExternalAction], lang: str) -> list[dict[str, Any]]:
    """Serialize action rows for the list endpoints (labels localized)."""
    rows: list[dict[str, Any]] = []
    with lang_override(lang):
        for action in queryset:
            link: ExternalLink = action.link
            rows.append(
                {
                    "id": link.identifier,
                    "label": link.label_i18n,
                    "url": link.url_i18n,
                    "template_vars": link.template_vars or None,
                    "order": action.order,
                }
            )
    return rows


def _filtered_actions(
    queryset: QuerySet[ExternalAction], kind: str | None, iso: str | None
) -> QuerySet[ExternalAction]:
    """Apply the kind/iso scope semantics (D2/D3) to a base queryset."""
    if kind:
        queryset = queryset.filter(Q(kinds__identifier=kind) | Q(kinds=None)).distinct()
    if iso:
        code = iso.upper()
        queryset = queryset.filter(
            Q(countries=[]) | Q(countries__contains=[code])
        ).distinct()
    return queryset.order_by("order", "pk")


class ExternalActionsController(ApiController):
    """Public open-in action list (CDN-cacheable)."""

    @modify(operation_id="get_external_actions")
    def get(self, parsed_query: Query[ActionsQuery]) -> list[dict[str, Any]]:
        """List open-in actions matching kind/iso (public rows).

        Open-in actions by app scope
        """
        queryset = ExternalAction.objects.filter(
            is_active=True, user__isnull=True
        ).select_related("link")
        return _action_rows(
            _filtered_actions(queryset, parsed_query.kind, parsed_query.iso),
            parsed_query.lang,
        )


class MyApiController(ApiController):
    """/v1/my/ namespace policy boundary (D5) — the ONE place.

    Every user-scoped controller inherits this base: bearer auth
    required (401 when absent — including when auth is disabled
    deployment-wide), ``Cache-Control: private, no-store`` on every
    response, and therefore never a CDN candidate (the
    ApiCdnCacheMiddleware only ever engages cacheable/public
    policies). The hut-page cache-poisoning class of bug becomes
    structurally impossible for user-scoped responses.
    """

    #: Applied to every operation of inheriting controllers (set in
    #: ``__init__`` — the base attribute type differs, so no override).
    _security_default: ClassVar[Any] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("security", [AuthBearer()])
        super().__init__(*args, **kwargs)

    @override
    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        response = super().dispatch(request, *args, **kwargs)
        response.headers["Cache-Control"] = "private, no-store"
        return response


class MyExternalActionsController(MyApiController):
    """The requester's open-in actions (private, never cached)."""

    @modify(operation_id="get_my_external_actions")
    def get(self, parsed_query: Query[ActionsQuery]) -> list[dict[str, Any]]:
        """List the authenticated user's open-in actions.

        Own open-in actions by app scope
        """
        user = getattr(self.request, "user", None)
        if user is None or not user.is_authenticated:
            raise APIError(
                {
                    "code": ErrorCode.not_authenticated,
                    "detail": "authentication required",
                },
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        queryset = ExternalAction.objects.filter(
            is_active=True, user=user
        ).select_related("link")
        return _action_rows(
            _filtered_actions(queryset, parsed_query.kind, parsed_query.iso),
            parsed_query.lang,
        )


class ExternalActionRenderController(ApiController):
    """Server-side URL render (QR/e-mail contexts; owner-checked)."""

    @modify(operation_id="render_external_action")
    def get(
        self,
        parsed_path: Path[RenderPath],
        parsed_query: Query[RenderQuery],
    ) -> dict[str, Any]:
        """Render an action's URL with the given template variables.

        Open-in action URL render
        """
        identifier = parsed_path.identifier
        link = ExternalLink.objects.filter(identifier=identifier).first()
        if link is None:
            raise_not_found("unknown action")
        user = getattr(self.request, "user", None)
        # AnonymousUser is not a valid user FK value — narrow before
        # the ORM tries to coerce it into a UUID and 500s.
        requester = user if (user and user.is_authenticated) else None
        visible = ExternalAction.objects.filter(link=link, is_active=True).filter(
            Q(user__isnull=True) | Q(user=requester)
        )
        if not visible.exists():
            raise_not_found("unknown action")
        params = {
            key: value
            for key, value in parsed_query.model_dump(exclude={"lang"}).items()
            if value is not None
        }
        # Built-in substitution vars beyond raw query params: {lang}
        # resolves via render_url's language parameter (SBB-style
        # ``/{lang}`` paths), {date} is the client's selected date or
        # defaults to tomorrow (ISO yyyy-mm-dd — the format SBB's
        # ``day=`` takes).
        if "date" in params:
            try:
                date.fromisoformat(str(params["date"]))
            except ValueError as error:
                raise APIError(
                    {
                        "code": ErrorCode.validation_error,
                        "detail": "date must be ISO yyyy-mm-dd",
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                ) from error
        else:
            params["date"] = (timezone.now() + timedelta(days=1)).date().isoformat()
        try:
            url = link.render_url(lang=parsed_query.lang, **params)
        except ValueError as error:
            raise APIError(
                {"code": ErrorCode.validation_error, "detail": str(error)},
                status_code=HTTPStatus.BAD_REQUEST,
            ) from error
        return {"id": link.identifier, "url": url}


paths = [
    path(
        "actions",
        ExternalActionsController.as_view(),
        name="get_external_actions",
    ),
    path(
        "actions/<str:identifier>",
        ExternalActionRenderController.as_view(),
        name="render_external_action",
    ),
]

#: User-scoped routes — mounted under the ``/v1/my/`` router prefix
#: (api_v1); the namespace policy lives on MyApiController.
my_paths = [
    path(
        "links/actions",
        MyExternalActionsController.as_view(),
        name="get_my_external_actions",
    ),
]
