"""Map layer models — the backend catalog for overlays and basemaps.

Design references: ``openspec/changes/map-layer-catalog/`` and
``_work/261012_overlays_basemaps_backend.md`` (decisions D1–D9).

Key invariants enforced here:

* ``(slug, spec, profile)`` is unique — the same logical layer may
  exist as device-tier variants (``low`` / ``medium`` / ``high``) ×
  capability profiles (``full`` / ``subset`` — openspec
  style-profiles-subset); the slug alone stays the identity for groups
  and (later) user preferences.
* Exactly one style source per layer: inline ``style`` JSONB (MapLibre
  ``StyleSpecification``) XOR ``style_url`` (externally authored style).
* Styles reference parameters as standalone JSON token nodes
  (``"{{param.slug}}"``); unknown tokens are rejected on save.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, override

from modeltrans.fields import TranslationField

from django.contrib.gis.db.models import MultiPolygonField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel

from . import validation

if TYPE_CHECKING:
    from django.db.models import QuerySet
else:
    try:  # runtime import for the isinstance check in pick_variant
        from django.db.models import QuerySet
    except ImportError:  # pragma: no cover
        QuerySet = None  # type: ignore[assignment]


class MapSlot(TimeStampedModel):
    """Insertion slot — where overlay layers render relative to the basemap.

    Rows, not code: adding a slot (e.g. a label-level slot for layers that
    must render above basemap labels) is a data change. Seeded with
    ``background`` (area overlays) and ``ways`` (line/symbol overlays).
    """

    slug = models.SlugField(
        max_length=30,
        unique=True,
        db_index=True,
        help_text=_("Stable slot identifier (referenced by layers)"),
    )
    label = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_("Human-readable slot name"),
    )
    i18n = TranslationField(fields=("label",))
    label_i18n: str
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text=_("Render order of the slot (lower renders beneath)"),
    )

    class Meta:
        verbose_name = _("Map slot")
        verbose_name_plural = _("Map slots")
        ordering = ("order", "slug")

    def __str__(self) -> str:
        return self.slug


class MapParameter(TimeStampedModel):
    """Customization knob referenced from styles as ``"{{slug}}"`` tokens.

    Scalars (``number``, ``color``, ``boolean``, ``enum``, ``string``,
    ``date``) render as simple controls; widget kinds (``opacity-curve``)
    hold a whole MapLibre expression subtree as their default and render
    as a curve editor. Shared across layers; per-layer defaults override
    via :class:`MapLayerParameter`. Value resolution is most-specific-wins:
    registry default < authored per-layer override < user global override
    < user per-layer override (user levels ship with the preferences lane).
    """

    class Kind(models.TextChoices):
        number = "number", _("number")
        color = "color", _("color")
        boolean = "boolean", _("boolean")
        enum = "enum", _("enum")
        string = "string", _("string")
        date = "date", _("date (runtime)")
        opacity_curve = "opacity-curve", _("opacity curve (widget)")

        @property
        def is_volatile(self) -> bool:
            """Serve-time (volatile) kinds rotate cache keys on their own clock."""
            return self.serve_time_value() is not None

        def serve_time_value(self, now: datetime | None = None) -> str | None:
            """Current value for serve-time (volatile) kinds, else ``None``.

            Volatile kinds bake a serve-time value into resolved style
            documents on their own clock — ``date`` resolves to the
            local date, so those bodies rotate daily. Every cache key
            derived from the content (render-cache digest, ``?v=``
            style-version token, catalog version) must fold this value
            in, or a cached/immutably-served document could outlive its
            content. ``now`` pins the clock for tests.
            """
            if self == self.date:
                current = (
                    timezone.localdate(now) if now is not None else timezone.localdate()
                )
                return current.isoformat()
            return None

    KINDS_SCALAR = (
        Kind.number,
        Kind.color,
        Kind.boolean,
        Kind.enum,
        Kind.string,
        Kind.date,
    )

    def serve_time_value(self, now: datetime | None = None) -> str | None:
        """Current serve-time value if this parameter is volatile, else None.

        Delegates to the kind's serve-time clock
        (:meth:`MapParameter.Kind.serve_time_value`). The field attribute
        is typed ``str`` (django-stubs), so the choices member is
        recovered first — no suppression needed.
        """
        return MapParameter.Kind(self.kind).serve_time_value(now)

    slug = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_("Token name referenced in styles as {{slug}} (dots allowed)"),
    )
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.number,
        db_index=True,
        help_text=_("Value type; determines the settings-tab control"),
    )
    label = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_("Human-readable label"),
    )
    description = models.TextField(
        max_length=400,
        default="",
        blank=True,
        help_text=_("Explanation shown in the settings UI"),
    )
    i18n = TranslationField(fields=("label", "description"))
    label_i18n: str
    description_i18n: str
    default = models.JSONField(
        null=True,
        blank=True,
        help_text=_(
            "Default value: scalar, or for widget kinds a MapLibre expression subtree"
        ),
    )
    constraints = models.JSONField(
        null=True,
        blank=True,
        help_text=_(
            "Kind-specific constraints (min/max/step/options; stop count for widgets)"
        ),
    )

    class Meta:
        verbose_name = _("Map parameter")
        verbose_name_plural = _("Map parameters")
        ordering = ("kind", "slug")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=[
                        "number",
                        "color",
                        "boolean",
                        "enum",
                        "string",
                        "date",
                        "opacity-curve",
                    ]
                ),
                name="basemaps_mapparameter_kind_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{{{{{self.slug}}}}} ({self.kind})"


class MapCoverage(TimeStampedModel):
    """Clip/coverage polygon (PostGIS) — the country-clip building block.

    Minimal phase-1 shape (WEP010 phase 1 extends this when it lands):
    slug, name, provenance, geometry. The catalog exports each layer's
    coverage as a bbox so clients implement country clipping client-side.
    """

    slug = models.SlugField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_("Stable coverage identifier"),
    )
    name = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_("Human-readable name (e.g. 'Switzerland + Liechtenstein')"),
    )
    provenance = models.TextField(
        max_length=400,
        default="",
        blank=True,
        help_text=_("Data source note (e.g. 'Natural Earth 10m, public domain')"),
    )
    geometry = MultiPolygonField(
        srid=4326,
        help_text=_("Coverage multipolygon (WGS84)"),
    )

    class Meta:
        verbose_name = _("Map coverage")
        verbose_name_plural = _("Map coverages")
        ordering = ("slug",)

    def __str__(self) -> str:
        return self.slug

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        """West, south, east, north bounds of the coverage."""
        extent = self.geometry.extent  # type: ignore[attr-defined]
        if not extent:
            return None
        return tuple(extent)


class MapLegend(TimeStampedModel):
    """A layer legend — sections of items explaining the layer's data.

    Slug-level by design: every variant (spec) row of a layer points at
    the same legend (per-variant divergence is possible but discouraged
    — a legend explains the data, which does not change with device
    tier). Category-driven sections resolve their items from the
    category tree at serve time; static items carry colors/widths that
    MAY reference parameter tokens (``{{param}}``) so legends reflect
    user-customized values (resolved client-side like style tokens).
    """

    title = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_("Legend title (fallback: layer name)"),
    )
    description = models.TextField(
        max_length=1000,
        default="",
        blank=True,
        help_text=_("Legend intro text"),
    )
    i18n = TranslationField(fields=("title", "description"))
    title_i18n: str
    description_i18n: str

    links = models.ManyToManyField(
        "external_links.ExternalLink",
        through="MapLegendLink",
        related_name="map_legends",
        blank=True,
        verbose_name=_("Links"),
        help_text=_("Related external links (more info, sources)"),
    )

    if TYPE_CHECKING:
        # Reverse relations (typed for checkers).
        sections: QuerySet[MapLegendSection]
        legend_links: QuerySet[MapLegendLink]
        layers: QuerySet[MapLayer]

    class Meta:
        verbose_name = _("Map legend")
        verbose_name_plural = _("Map legends")
        ordering = ("pk",)

    def __str__(self) -> str:
        target = self.layers.first() if hasattr(self, "layers") else None
        return f"Legend: {target.slug}" if target else f"Legend #{self.pk}"


class MapLegendSection(TimeStampedModel):
    """Ordered legend section — category-driven or static items."""

    class Type(models.TextChoices):
        symbol_detailed = "symbol_detailed", _("detailed symbols")
        symbol_simple = "symbol_simple", _("simple symbols")
        symbol_mono = "symbol_mono", _("monochrome symbols")
        symbol_dual = "symbol_dual", _("dual symbols")
        line = "line", _("lines")
        area = "area", _("areas")
        point = "point", _("points")

    legend = models.ForeignKey(
        MapLegend,
        on_delete=models.CASCADE,
        related_name="sections",
        db_index=True,
    )
    order = models.PositiveSmallIntegerField(default=0, db_index=True)
    title = models.CharField(max_length=100, default="", blank=True)
    title_i18n: str
    description_i18n: str
    description = models.TextField(max_length=400, default="", blank=True)
    i18n = TranslationField(fields=("title", "description"))
    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.symbol_detailed,
        help_text=_("How items in this section render"),
    )
    category = models.ForeignKey(
        "categories.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="legend_sections",
        db_index=True,
        help_text=_(
            "Category-driven section: items resolve from this category "
            "tree (overrides static items)"
        ),
    )

    class Meta:
        verbose_name = _("Legend section")
        verbose_name_plural = _("Legend sections")
        ordering = ("legend", "order", "pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    type__in=[
                        "symbol_detailed",
                        "symbol_simple",
                        "symbol_mono",
                        "symbol_dual",
                        "line",
                        "area",
                        "point",
                    ]
                ),
                name="basemaps_maplegendsection_type_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.title or f"Section #{self.pk}"


class MapLegendItem(TimeStampedModel):
    """Static legend item — values may reference parameter tokens."""

    section = models.ForeignKey(
        MapLegendSection,
        on_delete=models.CASCADE,
        related_name="items",
        db_index=True,
    )
    label_i18n: str
    description_i18n: str
    order = models.PositiveSmallIntegerField(default=0, db_index=True)
    label = models.CharField(max_length=100, default="", blank=True)
    description = models.TextField(max_length=400, default="", blank=True)
    i18n = TranslationField(fields=("label", "description"))
    color = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_(
            "Item color (hex) — may reference a parameter token like "
            "{{trail_color}} so the legend follows user customization"
        ),
    )
    width = models.CharField(
        max_length=50,
        default="",
        blank=True,
        help_text=_(
            "Line/size value — may reference a parameter token (e.g. {{trail_width}})"
        ),
    )
    icon = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_("Icon library reference (optional)"),
    )

    class Meta:
        verbose_name = _("Legend item")
        verbose_name_plural = _("Legend items")
        ordering = ("section", "order", "pk")

    def __str__(self) -> str:
        return self.label or f"Item #{self.pk}"


class MapLegendLink(TimeStampedModel):
    """Ordered legend ↔ external link join."""

    legend = models.ForeignKey(
        MapLegend,
        on_delete=models.CASCADE,
        related_name="legend_links",
        db_index=True,
    )
    link = models.ForeignKey(
        "external_links.ExternalLink",
        on_delete=models.CASCADE,
        related_name="legend_link_joins",
        db_index=True,
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("Legend link")
        verbose_name_plural = _("Legend links")
        ordering = ("legend", "order", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("legend", "link"),
                name="unique_legend_link",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.legend} ← {self.link}"


class MapLayer(TimeStampedModel):
    """A map layer: overlay or basemap, one row per device-tier variant.

    WEP010's phase-2 model: overlays and basemaps are the same thing at
    the style level and differ only in ``role``. Basemap-only fields
    (anchors, preview, ``is_default``, ``fallback``) and overlay-only
    fields (slot, config) are nullable.
    """

    class Role(models.TextChoices):
        basemap = "basemap", _("basemap")
        overlay = "overlay", _("overlay")

    class Spec(models.TextChoices):
        low = "low", _("low (weak GPU)")
        medium = "medium", _("medium")
        high = "high", _("high (vector-capable)")

    class Profile(models.TextChoices):
        full = "full", _("full (complete MapLibre style)")
        subset = "subset", _("subset (Leaflet-class renderable)")

    #: Explicit device-tier fallback chains (map-layers-api): exact
    #: match first, then the chain, then the single remaining variant.
    #: ``medium`` degrades to the cheaper tier — a mid-tier device is
    #: never upgraded to the heaviest variant on a tie.
    SPEC_FALLBACKS: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("low", ("medium", "high")),
        ("medium", ("low", "high")),
        ("high", ("medium", "low")),
    )

    #: Capability preference within one tier for full-capable clients
    #: (style-profiles-subset D3): a subset document is a valid full
    #: style by construction, so it is the in-tier fallback — the tier
    #: (a device constraint) is respected before format richness.
    PROFILE_PREFERENCE: ClassVar[tuple[str, str]] = (
        Profile.full,
        Profile.subset,
    )

    slug = models.CharField(
        max_length=100,
        db_index=True,
        help_text=_(
            "Stable layer identity — shared across spec variants; groups "
            "and preferences reference the slug. Dots allowed "
            "(swisstopo layer names)."
        ),
    )
    spec = models.CharField(
        max_length=10,
        choices=Spec.choices,
        default=Spec.medium,
        db_index=True,
        help_text=_("Device tier this variant targets"),
    )
    profile = models.CharField(
        max_length=10,
        choices=Profile.choices,
        default=Profile.full,
        db_index=True,
        help_text=_(
            "Format richness of this variant's style document: 'full' "
            "is a complete MapLibre style; 'subset' is restricted to the "
            "subset whitelist — valid as a full style by construction, "
            "renderable by Leaflet-class engines."
        ),
    )
    version = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text=_(
            "Rules this document was validated against — the maplibre "
            "style-spec release for full rows (e.g. '26.4.4'), the subset "
            "revision for subset rows (e.g. '0.1'); empty for externally "
            "authored style_url rows. Not to be confused with the style "
            'document\'s internal "version": 8 field.'
        ),
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.overlay,
        db_index=True,
        help_text=_("basemap or overlay"),
    )
    name = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_("Layer name (menu label)"),
    )
    description = models.TextField(
        max_length=1000,
        default="",
        blank=True,
        help_text=_("Layer description (info sheet)"),
    )
    i18n = TranslationField(fields=("name", "description"))
    name_i18n: str
    description_i18n: str

    icon = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_(
            "Icon library reference 'pack/slug' (e.g. 'fluent-emoji/hiking-boot')"
        ),
    )
    icon_badge = models.CharField(
        max_length=100,
        default="",
        blank=True,
        help_text=_("Optional badge icon (e.g. a country flag from the icon library)"),
    )

    slot = models.ForeignKey(
        MapSlot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="layers",
        verbose_name=_("Slot"),
        help_text=_("Insertion slot for overlays (ignored for basemaps)"),
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text=_("Display/render order within the role"),
    )
    show = models.BooleanField(
        default=True,
        help_text=_("Show in the layer menu"),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Included in catalog and style serving"),
    )
    is_default = models.BooleanField(
        default=False,
        help_text=_("Default basemap (role=basemap only)"),
    )

    min_zoom = models.FloatField(
        null=True,
        blank=True,
        help_text=_("Layer zoom floor"),
    )
    max_zoom = models.FloatField(
        null=True,
        blank=True,
        help_text=_("Layer zoom ceiling"),
    )

    style = models.JSONField(
        null=True,
        blank=True,
        help_text=_(
            "Inline MapLibre StyleSpecification (raster/vector/geojson "
            "sources; '{{token}}' parameter nodes allowed)"
        ),
    )
    style_url = models.URLField(
        null=True,
        blank=True,
        max_length=500,
        help_text=_(
            "Externally authored style URL (MapTiler, swisstopo, "
            "OpenFreeMap); '{{env:NAME}}' tokens allowed (resolved "
            "server-side)"
        ),
    )

    config = models.JSONField(
        null=True,
        blank=True,
        help_text=_(
            "Overlay config layout: filters, legend sections, links "
            "(category refs by slug)"
        ),
    )
    interaction = models.JSONField(
        null=True,
        blank=True,
        help_text=_(
            "Interaction hints: clickable layer ids and behaviors (e.g. hut detail)"
        ),
    )

    coverage = models.ForeignKey(
        MapCoverage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="layers",
        verbose_name=_("Coverage"),
        help_text=_("Clip polygon — catalog exports its bbox"),
    )
    fallback_min_zoom = models.FloatField(
        null=True,
        blank=True,
        help_text=_(
            "Below this zoom the variant hides and the fallback beneath "
            "shows (country rasters)"
        ),
    )
    fallback = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fallback_layers",
        verbose_name=_("Fallback layer"),
        help_text=_("Basemap auto-switch target when this one fails"),
    )

    anchors = models.JSONField(
        null=True,
        blank=True,
        help_text=_(
            "Basemap insertion anchors for overlay slots: "
            "{'ways': {'before': 'LayerId'}, 'background': {...}}"
        ),
    )
    preview_url = models.URLField(
        null=True,
        blank=True,
        max_length=500,
        help_text=_("Preview thumbnail URL (basemap switch)"),
    )

    license = models.ForeignKey(
        "licenses.License",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="map_layers",
        verbose_name=_("License"),
        help_text=_("License under which this layer's data is used"),
    )
    legend = models.ForeignKey(
        MapLegend,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="layers",
        verbose_name=_("Legend"),
        help_text=_(
            "This variant row's legend (per-spec divergence possible; "
            "sharing one legend row across variants is the seed default)"
        ),
    )

    parameters = models.ManyToManyField(
        MapParameter,
        through="MapLayerParameter",
        related_name="layers",
        blank=True,
        verbose_name=_("Parameters"),
        help_text=_("Customization knobs referenced from the style"),
    )
    categories = models.ManyToManyField(
        "categories.Category",
        through="MapLayerCategory",
        related_name="map_layers",
        blank=True,
        verbose_name=_("Categories"),
        help_text=_("Category links powering filters and legends"),
    )
    attributions = models.ManyToManyField(
        "organizations.Organization",
        through="MapLayerAttribution",
        related_name="map_layers",
        blank=True,
        verbose_name=_("Attributions"),
        help_text=_("Required attributions (org.attribution is the payload)"),
    )

    if TYPE_CHECKING:
        # Reverse relations to the through models (typed for checkers).
        layer_parameters: QuerySet[MapLayerParameter]
        layer_categories: QuerySet[MapLayerCategory]
        layer_attributions: QuerySet[MapLayerAttribution]
        fallback_layers: QuerySet[MapLayer]
        fallback_id: int | None

    class Meta:
        verbose_name = _("Map layer")
        verbose_name_plural = _("Map layers")
        ordering = ("role", "order", "slug", "spec", "profile")
        constraints = [
            models.UniqueConstraint(
                fields=("slug", "spec", "profile"),
                name="unique_slug_spec_profile_variant",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(style__isnull=False, style_url__isnull=True)
                    | models.Q(style__isnull=True, style_url__isnull=False)
                ),
                name="style_xor_style_url",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=["basemap", "overlay"]),
                name="%(app_label)s_%(class)s_role_valid".replace(
                    "%(app_label)s_%(class)s", "basemaps_maplayer"
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(spec__in=["low", "medium", "high"]),
                name="basemaps_maplayer_spec_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(profile__in=["full", "subset"]),
                name="basemaps_maplayer_profile_valid",
            ),
        ]
        indexes = [
            models.Index(fields=("role", "is_active", "order")),
        ]

    def __str__(self) -> str:
        return f"{self.slug} [{self.spec}/{self.profile}] ({self.role})"

    # ── Validation ────────────────────────────────────────────────────────

    @override
    def clean(self) -> None:
        """Structural + token + attribution validation (admin & factory)."""
        super().clean()
        errors: dict[str, str] = {}

        if self.style is not None:
            try:
                validation.validate_style_spec(self.style)
            except validation.StyleValidationError as exc:
                errors["style"] = str(exc)

            known = self._linked_parameter_slugs()
            unknown = validation.unknown_tokens(self.style) - known
            if unknown:
                errors["style"] = (
                    f"Unknown parameter token(s): "
                    f"{', '.join(sorted('{{' + t + '}}' for t in unknown))}"
                )

            # Subset rows gate on the whitelist walker (admin edits; the
            # seed upsert calls it directly — update_or_create bypasses
            # clean(), see map_seed._seed_layer_variant).
            if self.profile == self.Profile.subset and "style" not in errors:
                try:
                    validation.validate_subset_style(self.style)
                except validation.StyleValidationError as exc:
                    errors["style"] = str(exc)

        if self.style is not None and not self.version.strip():
            errors["version"] = (
                "Inline styles must record the rules version they were "
                "validated against (style-spec release or subset revision)."
            )
        if self.version and not validation.VERSION_RE.match(self.version):
            errors["version"] = (
                f"Version must be dotted decimals (e.g. '26.4.4', '0.1'), "
                f"got {self.version!r}."
            )

        if isinstance(self.config, dict) and "clustering" in self.config:
            try:
                validation.validate_clustering_config(self.config["clustering"])
            except validation.StyleValidationError as exc:
                errors["config"] = str(exc)

        if self.style_url and validation.unknown_env_tokens(self.style_url):
            errors["style_url"] = "Malformed env token (expected {{env:NAME}})"

        external = self._has_external_sources()
        if external and self.pk and not self.attributions.exists():
            errors["attributions"] = (
                "Layers referencing third-party sources require at least "
                "one attribution."
            )

        if errors:
            raise ValidationError(errors)

    def _linked_parameter_slugs(self) -> set[str]:
        """Slugs of parameters linked to this layer (pending M2M safe)."""
        if self.pk is None:
            return set()
        return set(
            MapLayerParameter.objects.filter(layer_id=self.pk).values_list(
                "parameter__slug", flat=True
            )
        )

    def _has_external_sources(self) -> bool:
        """True when the layer references third-party tile/data sources."""
        if self.style_url:
            return True
        if not self.style:
            return False
        return validation.has_external_sources(
            self.style, local_hosts=validation.local_hosts()
        )

    # ── Serving helpers ───────────────────────────────────────────────────

    def missing_env(self) -> set[str]:
        """Env names this layer needs that the deployment cannot resolve.

        Empty for layers without ``{{env:…}}`` tokens. A non-empty
        result means the layer cannot be served — its style or external
        ``style_url`` would leak literal tokens — so the API gates it
        out of the catalog and the style endpoint (see api.py).
        """
        from .resolution import missing_env_names

        document = self.style if self.style is not None else (self.style_url or "")
        return missing_env_names(document)

    def authored_parameter_values(self) -> dict[str, object]:
        """Authored resolution level: registry defaults + layer overrides."""
        values: dict[str, object] = {}
        links = MapLayerParameter.objects.filter(layer=self).select_related("parameter")
        for link in links:
            default = link.parameter.default
            values[link.parameter.slug] = (
                link.default_override if link.default_override is not None else default
            )
        return values

    def serve_time_parameter_values(
        self, now: datetime | None = None
    ) -> dict[str, str]:
        """Serve-time values of this layer's volatile parameters.

        The one place that knows a layer's style documents rotate on a
        clock (``Kind.is_volatile``): the serve-time default injection,
        the render-cache digest and the ``?v=`` style-version token all
        consume this, so they cannot drift apart (see api.py). Empty for
        layers without volatile parameters. ``now`` pins the clock for
        tests.
        """
        values: dict[str, str] = {}
        for link in self.layer_parameters.all():
            served = link.parameter.serve_time_value(now)
            if served is not None:
                values[link.parameter.slug] = served
        return values

    @classmethod
    def pick_variant(
        cls,
        queryset: QuerySet[MapLayer] | Sequence[MapLayer],
        spec: str | None = None,
        profile: str | None = None,
    ) -> MapLayer | None:
        """Select the variant: tier chain × capability profile.

        Tier walk (cheap-first for ``medium``): ``low → medium → high``,
        ``medium → low → high``, ``high → medium → low``. With no
        requested spec the first row serves; an unknown spec falls back
        to the single/first variant (query models reject invalid values
        before this point).

        The capability profile (style-profiles-subset D3):

        * ``None`` — today's behavior: profile-agnostic tier walk,
          preferring ``full`` when both profiles exist at a tier.
        * ``"full"`` — per tier prefer ``full`` then ``subset`` (a
          subset document is a valid full style by construction); the
          tier is respected before format richness.
        * ``"subset"`` — subset rows only, walking the same tier
          order; ``None`` when the slug has no subset variant (the
          slug is then absent from subset-resolved views).
        """
        if isinstance(queryset, QuerySet):
            layers = list(queryset.filter(is_active=True))
        else:
            layers = [layer for layer in queryset if layer.is_active]
        if profile == cls.Profile.subset:
            layers = [layer for layer in layers if layer.profile == cls.Profile.subset]
        if not layers:
            return None
        if spec is None:
            return layers[0]
        by_pair = {(layer.spec, layer.profile): layer for layer in layers}
        tiers = (spec, *dict(cls.SPEC_FALLBACKS).get(spec, ()))
        if profile == cls.Profile.full:
            for tier in tiers:
                for candidate in cls.PROFILE_PREFERENCE:
                    picked = by_pair.get((tier, candidate))
                    if picked is not None:
                        return picked
            return layers[0]
        # Profile-agnostic (today) or subset (already filtered): the
        # plain tier walk, preferring full over subset within a tier.
        by_spec: dict[str, MapLayer] = {}
        for layer in layers:
            current = by_spec.get(layer.spec)
            if current is None or (
                current.profile == cls.Profile.subset
                and layer.profile == cls.Profile.full
            ):
                by_spec[layer.spec] = layer
        for tier in tiers:
            picked = by_spec.get(tier)
            if picked is not None:
                return picked
        return layers[0]


class MapLayerParameter(TimeStampedModel):
    """Layer ↔ parameter link with optional authored default override."""

    layer = models.ForeignKey(
        MapLayer,
        on_delete=models.CASCADE,
        related_name="layer_parameters",
        db_index=True,
    )
    parameter = models.ForeignKey(
        MapParameter,
        on_delete=models.CASCADE,
        related_name="layer_links",
        db_index=True,
    )
    default_override = models.JSONField(
        null=True,
        blank=True,
        help_text=_("Authored per-layer default (wins over registry default)"),
    )

    class Meta:
        verbose_name = _("Layer parameter")
        verbose_name_plural = _("Layer parameters")
        ordering = ("parameter__slug",)
        constraints = [
            models.UniqueConstraint(
                fields=("layer", "parameter"),
                name="unique_layer_parameter",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.layer} ← {self.parameter}"


class MapLayerCategory(TimeStampedModel):
    """Layer ↔ category link powering filters and legends."""

    class Use(models.TextChoices):
        primary = "primary", _("primary")
        filter = "filter", _("filter")
        legend = "legend", _("legend")

    layer = models.ForeignKey(
        MapLayer,
        on_delete=models.CASCADE,
        related_name="layer_categories",
        db_index=True,
    )
    category = models.ForeignKey(
        "categories.Category",
        on_delete=models.CASCADE,
        related_name="layer_links",
        db_index=True,
    )
    use = models.CharField(
        max_length=10,
        choices=Use.choices,
        default=Use.primary,
        db_index=True,
        help_text=_("What the category powers for this layer"),
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text=_("Order within the use group"),
    )

    class Meta:
        verbose_name = _("Layer category")
        verbose_name_plural = _("Layer categories")
        ordering = ("layer", "use", "order", "category__slug")
        constraints = [
            models.UniqueConstraint(
                fields=("layer", "category", "use"),
                name="unique_layer_category_use",
            ),
            models.CheckConstraint(
                condition=models.Q(use__in=["primary", "filter", "legend"]),
                name="basemaps_maplayercategory_use_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.layer} ← {self.category} ({self.use})"


class MapLayerAttribution(TimeStampedModel):
    """Layer ↔ organization attribution link (ordered)."""

    layer = models.ForeignKey(
        MapLayer,
        on_delete=models.CASCADE,
        related_name="layer_attributions",
        db_index=True,
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="layer_attribution_links",
        db_index=True,
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text=_("Attribution display order"),
    )

    class Meta:
        verbose_name = _("Layer attribution")
        verbose_name_plural = _("Layer attributions")
        ordering = ("layer", "order", "organization__slug")
        constraints = [
            models.UniqueConstraint(
                fields=("layer", "organization"),
                name="unique_layer_attribution",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.layer} ← {self.organization}"


class TileAssetVersion(TimeStampedModel):
    """Content version of a tile-server asset group — the `?v=` source.

    Keys are stable slugs; the canonical ones written by the Martin
    watcher are ``sprites`` (hash over every probed sprite sheet's served
    bytes) and ``fonts`` (hash over one glyph range per referenced font
    stack). ``external`` entries are keyed by URL and are bumped by the
    daily verifier (or manually from the admin — the only origin where
    ``version`` is editable).

    Tile-source versions (e.g. the huts aggregate) are NOT stored here —
    they are computed at serve time (``basemaps.tile_assets``).
    """

    class Origin(models.TextChoices):
        martin_sync = "martin_sync", _("martin sync (observed bytes)")
        external = "external", _("external asset (verified / manual)")

    # CharField, not SlugField: external keys are URLs (colons, dots,
    # slashes — validate_slug would reject them).
    key = models.CharField(
        unique=True,
        max_length=200,
        help_text=_("Stable key: 'sprites', 'fonts', or the external URL"),
    )
    version = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=_("Short content hash; empty = not yet published"),
    )
    origin = models.CharField(
        max_length=20,
        choices=Origin.choices,
        default=Origin.martin_sync,
    )
    etag = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text=_("External verifier: last observed ETag validator"),
    )
    last_modified = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=_("External verifier: last observed Last-Modified validator"),
    )
    last_checked = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("External verifier: last successful probe"),
    )

    class Meta:
        verbose_name = _("Tile asset version")
        verbose_name_plural = _("Tile asset versions")
        ordering = ("origin", "key")

    def __str__(self) -> str:
        return f"{self.key} @ {self.version or '∅'}"
