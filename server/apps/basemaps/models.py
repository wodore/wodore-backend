"""Map layer models — the backend catalog for overlays and basemaps.

Design references: ``openspec/changes/map-layer-catalog/`` and
``_work/261012_overlays_basemaps_backend.md`` (decisions D1–D9).

Key invariants enforced here:

* ``(slug, spec)`` is unique — the same logical layer may exist as
  device-tier variants (``low`` / ``medium`` / ``high``); the slug alone
  stays the identity for groups and (later) user preferences.
* Exactly one style source per layer: inline ``style`` JSONB (MapLibre
  ``StyleSpecification``) XOR ``style_url`` (externally authored style).
* Styles reference parameters as standalone JSON token nodes
  (``"{{param.slug}}"``); unknown tokens are rejected on save.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from modeltrans.fields import TranslationField

from django.contrib.gis.db.models import MultiPolygonField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel

from . import validation

if TYPE_CHECKING:
    from django.db.models import QuerySet


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

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
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

    KINDS_SCALAR = (
        Kind.number,
        Kind.color,
        Kind.boolean,
        Kind.enum,
        Kind.string,
        Kind.date,
    )

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

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
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

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
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

    SPEC_ORDER: ClassVar[tuple[str, ...]] = ("low", "medium", "high")

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

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Map layer")
        verbose_name_plural = _("Map layers")
        ordering = ("role", "order", "slug", "spec")
        constraints = [
            models.UniqueConstraint(
                fields=("slug", "spec"),
                name="unique_slug_spec_variant",
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
        ]
        indexes = [
            models.Index(fields=("role", "is_active", "order")),
        ]

    def __str__(self) -> str:
        return f"{self.slug} [{self.spec}] ({self.role})"

    # ── Validation ────────────────────────────────────────────────────────

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

    @classmethod
    def pick_variant(
        cls, queryset: QuerySet[MapLayer], spec: str | None
    ) -> MapLayer | None:
        """Select the device-tier variant: exact → nearest → single.

        A low-tier request with only a ``high`` variant serves it, and
        vice versa (spec scenario 'Fallback in both directions').
        """
        layers = list(queryset.filter(is_active=True))
        if not layers:
            return None
        if spec is None:
            return layers[0]
        by_spec = {layer.spec: layer for layer in layers}
        if spec in by_spec:
            return by_spec[spec]
        order = list(cls.SPEC_ORDER)
        try:
            idx = order.index(spec)
        except ValueError:
            return layers[0]
        for distance in range(1, len(order)):
            for candidate_idx in (idx + distance, idx - distance):
                if 0 <= candidate_idx < len(order):
                    candidate = order[candidate_idx]
                    if candidate in by_spec:
                        return by_spec[candidate]
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

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
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

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
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

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
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
