"""Place-level seasonality: the monthly standard share.

OpenSpec ``geoplace-kinds-operations-graph`` (task 2.2): one row per
place (only where data exists) with twelve month columns, each NULL
(unknown) or 0–100 — the **standard share** for that month: 100 =
only standard mode operates, 0 = only reduced (what "reduced" means
rides on the reduced association's category — winter room, self-
service, or closed; a below-100 month with no reduced type resolves
the reduced mode to ``accommodation.unknown``), values between =
temporal split within the month. Fuzzy source vocabulary maps
deterministically (yes=100 … no=0, unknown=NULL).

The 1-based ``Month`` IntEnum + dict-like ``MonthAccessor`` (ported
from draft PR #154) keep the numbered columns safe to touch.
"""

from collections.abc import Iterator
from enum import IntEnum
from typing import Any

from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel


class Month(IntEnum):
    """1-based calendar months (column month_01 … month_12)."""

    JANUARY = 1
    FEBRUARY = 2
    MARCH = 3
    APRIL = 4
    MAY = 5
    JUNE = 6
    JULY = 7
    AUGUST = 8
    SEPTEMBER = 9
    OCTOBER = 10
    NOVEMBER = 11
    DECEMBER = 12


#: hut-services fuzzy vocabulary → standard share (design D4).
FUZZY_MONTH_SHARE: dict[str, int | None] = {
    "yes": 100,
    "yesish": 75,
    "maybe": 50,
    "noish": 25,
    "no": 0,
    "unknown": None,
}


#: Combined range constraint: every month NULL or 0–100.
_SHARES_0_100 = models.Q()
for _m in Month:
    _col = f"month_{_m.value:02d}"
    _SHARES_0_100 &= models.Q(**{f"{_col}__isnull": True}) | (
        models.Q(**{f"{_col}__gte": 0}) & models.Q(**{f"{_col}__lte": 100})
    )


class MonthAccessor:
    """Dict-like view over the twelve month columns.

    ``season.months[Month.JULY] = 100`` / reads / ``to_dict()``
    round-trips; ``TypeError`` for non-Month keys, ``ValueError`` for
    values outside 0–100. NULL columns read as ``None``.
    """

    __slots__ = ("_instance",)

    def __init__(self, instance: "GeoPlaceSeasonality") -> None:
        self._instance = instance

    def _column(self, month: Month) -> str:
        return f"month_{month.value:02d}"

    def __getitem__(self, key: Month) -> int | None:
        if not isinstance(key, Month):
            msg = f"month key must be a Month enum member, got {key!r}"
            raise TypeError(msg)
        return getattr(self._instance, self._column(key))

    def __setitem__(self, key: Month, value: int | None) -> None:
        if not isinstance(key, Month):
            msg = f"month key must be a Month enum member, got {key!r}"
            raise TypeError(msg)
        if value is not None and not (0 <= value <= 100):
            msg = f"standard share must be within 0–100, got {value!r}"
            raise ValueError(msg)
        setattr(self._instance, self._column(key), value)

    def __iter__(self) -> Iterator[tuple[Month, int | None]]:
        for month in Month:
            yield month, self[month]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, Month)

    def to_dict(self) -> dict[Month, int | None]:
        """Snapshot as ``{Month: share}`` (round-trips via update)."""
        return dict(self)

    @classmethod
    def from_dict(cls, instance: "GeoPlaceSeasonality", months: Any) -> None:
        """Write ``{Month|int: share}`` onto the instance's columns."""
        for key, value in dict(months).items():
            month = key if isinstance(key, Month) else Month(int(key))
            instance.months[month] = value


def _month_field(month: Month) -> models.IntegerField[Any, Any]:
    return models.IntegerField(
        null=True,
        blank=True,
        verbose_name=month.name.capitalize(),
        help_text=_("Standard share 0–100 (100 = only standard, 0 = only reduced)"),
    )


class GeoPlaceSeasonality(TimeStampedModel):
    """Monthly standard share of a place's operation modes."""

    #: FK id attribute — plugin-less inference gap (pyrefly idiom).
    geo_place_id: int

    geo_place = models.OneToOneField(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="seasonality",
        verbose_name=_("Geo Place"),
    )
    month_01 = _month_field(Month.JANUARY)
    month_02 = _month_field(Month.FEBRUARY)
    month_03 = _month_field(Month.MARCH)
    month_04 = _month_field(Month.APRIL)
    month_05 = _month_field(Month.MAY)
    month_06 = _month_field(Month.JUNE)
    month_07 = _month_field(Month.JULY)
    month_08 = _month_field(Month.AUGUST)
    month_09 = _month_field(Month.SEPTEMBER)
    month_10 = _month_field(Month.OCTOBER)
    month_11 = _month_field(Month.NOVEMBER)
    month_12 = _month_field(Month.DECEMBER)

    class Meta:
        verbose_name = _("Geo Place Seasonality")
        verbose_name_plural = _("Geo Place Seasonalities")
        constraints = [
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_shares_0_100",
                condition=_SHARES_0_100,
            ),
        ]

    def __str__(self) -> str:
        return f"seasonality[{self.geo_place_id}]"

    @property
    def months(self) -> MonthAccessor:
        """Dict-like month access (``season.months[Month.JULY]``)."""
        return MonthAccessor(self)
