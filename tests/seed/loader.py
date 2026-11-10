"""Seed data loader for test infrastructure.

Reads YAML seed files and creates model instances with all relations.
Slug is auto-generated on save by the model's save() method.

Also home of the flush-restore machinery (``restore_post_flush``):
baseline data pytest-django's transactional-test teardown destroys and
this module puts back (see its docstring for the full story).
"""

import hashlib
import pathlib

import yaml

from django.contrib.gis.geos import GEOSGeometry

from server.apps.categories.models import Category
from server.apps.contacts.models import Contact, ContactFunction
from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import (
    Hut,
    HutContactAssociation,
    HutOrganizationAssociation,
)
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
    # (map tree: accommodation lives under the amenity super-root)
    parent = (
        Category.objects.filter(slug="accommodation", parent__slug="amenity").first()
        or Category.objects.filter(slug="accommodation").first()
    )
    cat = Category.objects.create(
        slug=slug,
        name=slug.replace("_", " ").replace("-", " ").title(),
        parent=parent,
        is_active=True,
    )
    return cat


def _get_or_create_contact_function(slug: str) -> ContactFunction | None:
    """Look up or create a ContactFunction by slug.

    Returns None if slug is empty/falsy — callers should check.
    """
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
            domain=place_data.get("domain", "none"),
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


def seed_file_hash() -> str:
    """Compute a hash of all seed YAML files to detect changes."""
    hasher = hashlib.sha256()
    for seed_file in sorted(SEED_DIR.glob("*.yaml")):
        hasher.update(seed_file.read_bytes())
    return hasher.hexdigest()


def reset_pk_sequences() -> None:
    """Advance Postgres pk sequences past fixture-loaded explicit ids.

    Fixture files (e.g. organizations.yaml) carry explicit ``pk:``
    values; loading them does not advance the sequences, so later
    factory/ORM inserts collide with existing ids (duplicate key
    violations - seen live in CI and on staging). Idempotent.
    """
    from django.apps import apps
    from django.db import connection

    qn = connection.ops.quote_name
    with connection.cursor() as cursor:
        for model in apps.get_models():
            field = model._meta.auto_field
            if field is None:
                continue
            table = model._meta.db_table
            cursor.execute(
                "SELECT pg_get_serial_sequence(%s, %s)", [table, field.column]
            )
            seq = cursor.fetchone()[0]
            if not seq:
                continue
            cursor.execute(
                f"SELECT setval(%s, COALESCE((SELECT MAX({qn(field.column)})"  # type: ignore  # argument typing drift vs stubs
                f" FROM {qn(table)}), 0) + 1, false)",
                [seq],
            )


def vocabulary_intact() -> bool:
    """Whether the data-migration vocabulary survives in the database.

    The protected ``map`` root category is created by a data migration,
    never deleted by anything in the suite, and wiped by every flush —
    a cheap sentinel for "the baseline data is gone".
    """
    from server.apps.categories.models import Category

    return Category.objects.filter(slug="map", parent=None).exists()


def rebuild_gutted_test_database() -> bool:
    """Drop and re-migrate the test database when its baseline is gone.

    A session that died mid-transactional-test (hard crash, or a
    pre-fix run) leaves the database flushed: no data-migration rows,
    and nothing recorded-pending for ``migrate`` to re-apply — every
    restore of that session would rebuild from a poisoned snapshot.
    The only full-fidelity repair is rebuilding from scratch: destroy
    + re-create + re-migrate the test database (schema DDL is
    deterministic; the data migrations re-seed the vocabulary), then
    refresh ``connection._test_serialized_contents`` over the poisoned
    snapshot.

    Returns True when a rebuild ran (``vocabulary_intact`` was False).
    """
    import contextlib
    import io
    from typing import Any

    from django.db import connection

    if vocabulary_intact():
        return False

    # ``destroy_test_db`` restores settings_dict["NAME"] to the
    # original database; ``create_test_db`` then re-creates the test
    # database (test_<name>) and re-runs every migration from scratch.
    # Data migrations print unconditionally — keep the rebuild quiet.
    with contextlib.redirect_stdout(io.StringIO()):
        original_name = connection.settings_dict["NAME"]
        connection.creation.destroy_test_db(original_name, verbosity=0)
        connection.creation.create_test_db(verbosity=0, autoclobber=True)

    if getattr(connection, "_test_serialized_contents", None) is not None:
        # dynamic attribute (set by Django's test machinery, not in the
        # stubs) — typed local, the documented idiom
        conn_any: Any = connection
        conn_any._test_serialized_contents = (
            connection.creation.serialize_db_to_string()
        )
    return True


def restore_post_flush() -> bool:
    """Re-create the baseline data a pytest-django flush destroyed.

    pytest-django tears ``django_db(transaction=True)`` tests down with
    a full database ``flush`` (TRUNCATE of every model table — no
    rollback isolation). That wipes everything the rest of the suite
    silently relies on: rows written by DATA migrations (category
    vocabulary, uri kinds, extra schemas, ...), the organizations
    fixture, and the session-committed seed data. Any dependent test
    that runs after a transactional test then fails
    (``Category.DoesNotExist``, ``hut is None``, ...).

    ``django_migrations`` is NOT truncated (it is not an app-model
    table), so ``migrate`` never re-runs the data migrations. Instead,
    the conftest forces every transactional test onto Django's
    ``serialized_rollback`` machinery, which snapshots the pristine
    post-migrate database into
    ``connection._test_serialized_contents`` at session start — that
    snapshot is restored here. Deserialization carries explicit pks
    (save() is UPDATE-else-INSERT), so re-applying it over partially
    restored state is safe.

    When even the snapshot is poisoned (a reused test database that a
    previous session left flushed — crash, or a pre-fix run — was
    snapshotted as-is at session start), the restore re-deserializes
    nothing and the vocabulary stays missing; that case falls back to
    a full rebuild (``rebuild_gutted_test_database``).

    Returns True when a restore ran; the no-op path costs one EXISTS
    query on the protected ``map`` root category.
    """
    from django.core.cache import cache
    from django.db import connection

    if vocabulary_intact():
        return False

    snapshot: str | None = getattr(connection, "_test_serialized_contents", None)
    if snapshot is not None:
        connection.creation.deserialize_db_from_string(snapshot)

    if not vocabulary_intact():
        # The snapshot itself lacks the vocabulary — the session
        # started from a gutted reused database. Only a from-scratch
        # rebuild restores full fidelity (and refreshes the snapshot).
        rebuild_gutted_test_database()

    # A flush implies the seed data is gone with everything else
    # (nothing writes between the flush and this restore), so reload
    # whenever no hut survived — mirrors the seed_data fixture logic.
    if not Hut.objects.exists():
        load_all_seeds()
        cache.set("test_seed_hash", seed_file_hash())

    # The restored rows carry explicit pks; keep sequences ahead of
    # them for factory/ORM inserts.
    reset_pk_sequences()
    return True


def clear_seed_rows() -> None:
    """Delete the loader-owned seed rows (huts, geoplaces).

    Snapshot hygiene: the serialized baseline must not carry seed rows.
    On a reused test database the snapshot is taken from the leftover
    state — seed huts in it would be re-inserted (old pks) by Django's
    serialized-rollback deserialization and collide with freshly
    re-loaded seeds (new pks, same slugs). Seed state never needs to
    survive a session: ``seed_data`` detects the missing huts and
    reloads. Cascades clean up associations/sources; the category and
    organization rows the loader get_or_creates are idempotent and
    harmless to keep.
    """
    Hut.objects.all().delete()
    GeoPlace.objects.all().delete()
    reset_pk_sequences()
