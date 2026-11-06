"""Party domain services.

Shared logic for the owner merge — used by ``import_parties`` (task 3.1)
and the wodore hut import (task 3.2).
"""

from server.apps.external_links.models import ExternalLink
from server.apps.owners.models import Owner
from server.apps.parties.models import Party, PartyLink


def resolve_party_by_name(
    name: str, *, review_status: str | None = None
) -> tuple[Party, bool]:
    """Resolve a party by import identity, adopting same-named parties.

    The identity (``extra.osm_name``, OpenSpec ``party-slug-minting``)
    is the normalized name. When no row carries it yet, a party whose
    base ``name`` matches exactly is adopted — the identity is stamped
    onto it — so manually created parties dedupe with imports instead
    of duplicating. ``review_status`` applies to newly created rows
    only (get_or_create semantics). Returns ``(party, created)``.
    """
    key = Party.normalize_key(name)
    # Containment lookups (``extra__contains={"osm_name": key}``)
    # resolve the identity — the jsonb GIN index serves containment,
    # not ``->>`` equality (advisor review finding 3).
    party = Party.objects.filter(extra__contains={"osm_name": key}).first()
    if party is not None:
        return party, False
    same_name = Party.objects.filter(name=name).first()
    if same_name is not None:
        same_name.extra = {**(same_name.extra or {}), "osm_name": key}
        same_name.save(update_fields=["extra"])
        return same_name, False
    defaults: dict[str, object] = {"name": name, "extra": {"osm_name": key}}
    if review_status:
        defaults["review_status"] = review_status
    return Party.objects.get_or_create(
        extra__contains={"osm_name": key}, defaults=defaults
    )


def merge_owner(owner: Owner) -> tuple[Party, bool, bool]:
    """Merge an ``owners.Owner`` row into a ``Party`` (idempotent).

    Slug, localized name and note carry over (the ``i18n`` keys
    ``name_*``/``note_*`` — Owner and Party translate the same fields);
    a non-empty ``url`` becomes an ``ExternalLink`` attached via
    ``PartyLink`` (shared link entity, reused when the URL already
    exists). The private ``comment`` and the (data-empty) contacts M2M
    do not carry over.

    New links are created with an explicit label and
    ``skip_health_check`` — importing must not do network I/O.

    Returns ``(party, party_created, link_created)``.
    """
    i18n = {
        key: value
        for key, value in (owner.i18n or {}).items()
        if key.startswith(("name_", "note_"))
    }
    # Dedup by the normalized owner slug stored as the ``extra.osm_name``
    # import identity (OpenSpec ``party-slug-minting``): the slug is a
    # minted short public identifier, minted once on creation;
    # re-merges resolve through the identity. Owner slugs are already
    # normalized, so ``normalize_key`` is the identity here.
    key = Party.normalize_key(owner.slug)
    party, party_created = Party.objects.get_or_create(
        # Containment — served by the extra GIN index (advisor review
        # finding 3).
        extra__contains={"osm_name": key},
        defaults={
            "name": owner.name or owner.slug,
            "i18n": i18n,
            "extra": {"osm_name": key},
        },
    )

    link_created = False
    if owner.url:
        link = ExternalLink.objects.filter(url=owner.url).first()
        if link is None:
            link = ExternalLink(url=owner.url, label=owner.name or owner.slug)
            link.save(skip_health_check=True)
            link_created = True
        _association, association_created = PartyLink.objects.get_or_create(
            party=party, external_link=link
        )
        link_created = link_created or association_created

    return party, party_created, link_created
