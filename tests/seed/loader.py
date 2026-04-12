"""Seed data loader for test infrastructure.

Reads YAML seed files and creates model instances with all relations.
Slug is auto-generated on save by the model's save() method.
"""

import pathlib

import yaml
from django.contrib.gis.geos import GEOSGeometry

from server.apps.categories.models import Category
from server.apps.contacts.models import Contact, ContactFunction
from server.apps.huts.models import (
    Hut,
    HutContactAssociation,
    HutOrganizationAssociation,
)
from server.apps.geometries.models import GeoPlace
from server.apps.organizations.models import Organization


SEED_DIR = pathlib.Path(__file__).parent


def _parse_location(location_str: str):
    """Parse EWKT location string like 'SRID=4326;POINT (8.9649 46.8389)' to GEOS geometry."""
    return GEOSGeometry(location_str, srid=4326)


def _get_or_create_category(slug: str) -> Category | None:
    """Look up a category by slug, create under 'accommodation' parent if not found.

    In a test DB, hut-type categories (hut, bivouac, selfhut, etc.) may not
    exist because the data migration depends on HutType having data. This
    creates them on-the-fly so seed data always works.
    """
    # Try exact match first (any parent)
    cat = Category.objects.filter(slug=slug).first()
    if cat:
        return cat

    # Not found — create under 'accommodation' parent
    parent = Category.objects.filter(slug="accommodation", parent=None).first()
    cat = Category.objects.create(
        slug=slug,
        name=slug.replace("_", " ").replace("-", " ").title(),
        parent=parent,
        is_active=True,
    )
    return cat


def _get_or_create_contact_function(slug: str) -> ContactFunction | None:
    """Look up or create a ContactFunction by slug."""
    if not slug:
        return None
    func, _ = ContactFunction.objects.get_or_create(
        slug=slug,
        defaults={
            "name": slug.replace("_", " ").replace("-", " ").title(),
            "priority": 10,
        },
    )
    return func


def load_huts(seed_file: str = "huts.yaml") -> int:
    """Load huts from a YAML seed file. Returns the number of huts created."""
    filepath = SEED_DIR / seed_file
    if not filepath.exists():
        return 0

    with open(filepath) as f:
        data = yaml.safe_load(f)

    huts_data = data.get("huts", [])
    if not huts_data:
        return 0

    created = 0
    for hut_data in huts_data:
        hut_type_open = _get_or_create_category(hut_data.get("hut_type_open", "hut"))
        if hut_type_open is None:
            continue

        hut_type_closed = None
        if hut_data.get("hut_type_closed"):
            hut_type_closed = _get_or_create_category(hut_data["hut_type_closed"])

        hut = Hut(
            name=hut_data["name"],
            location=_parse_location(hut_data["location"]),
            elevation=hut_data.get("elevation"),
            country_field=hut_data.get("country", "CH"),
            hut_type_open=hut_type_open,
            hut_type_closed=hut_type_closed,
            capacity_open=hut_data.get("capacity_open"),
            capacity_closed=hut_data.get("capacity_closed"),
            is_active=True,
            is_public=True,
            review_status=Hut.ReviewStatusChoices.done,
        )
        hut.save()

        # Link organizations
        for org_data in hut_data.get("organizations", []):
            org_slug = org_data["slug"]
            org, _ = Organization.objects.get_or_create(
                slug=org_slug,
                defaults={
                    "name": org_slug.upper(),
                    "is_active": True,
                    "is_public": True,
                },
            )
            HutOrganizationAssociation.objects.create(
                hut=hut,
                organization=org,
                source_id=org_data.get("source_id", ""),
            )

        # Link contacts
        for i, contact_data in enumerate(hut_data.get("contacts", [])):
            function = _get_or_create_contact_function(
                contact_data.get("function_slug", "")
            )
            contact = Contact(
                name=contact_data.get("name", ""),
                email=contact_data.get("email", ""),
                phone=contact_data.get("phone", ""),
                function=function,
                is_active=True,
                is_public=True,
            )
            contact.save()
            HutContactAssociation.objects.create(
                hut=hut,
                contact=contact,
                order=i,
            )

        created += 1

    return created


def load_geoplaces(seed_file: str = "geoplaces.yaml") -> int:
    """Load geoplaces from a YAML seed file. Returns the number of geoplaces created."""
    filepath = SEED_DIR / seed_file
    if not filepath.exists():
        return 0

    with open(filepath) as f:
        data = yaml.safe_load(f)

    geoplaces_data = data.get("geoplaces", [])
    if not geoplaces_data:
        return 0

    created = 0
    for place_data in geoplaces_data:
        place = GeoPlace(
            name=place_data["name"],
            location=_parse_location(place_data["location"]),
            elevation=place_data.get("elevation"),
            country_code=place_data.get("country", "CH"),
            importance=place_data.get("importance", 25),
            detail_type=place_data.get("detail_type", "none"),
            is_active=True,
            is_public=True,
            review_status="done",
        )
        place.save()

        # Link categories
        for cat_slug in place_data.get("category_slugs", []):
            cat = _get_or_create_category(cat_slug)
            if cat:
                place.categories.add(cat)

        created += 1

    return created


def load_all_seeds() -> dict[str, int]:
    """Load all seed files. Returns dict with counts per model."""
    results = {}
    results["huts"] = load_huts()
    results["geoplaces"] = load_geoplaces()
    return results
