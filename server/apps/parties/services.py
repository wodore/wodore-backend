"""Party domain services.

Shared logic for the owner merge — used by ``import_parties`` (task 3.1)
and the wodore hut import (task 3.2).
"""

from server.apps.external_links.models import ExternalLink
from server.apps.owners.models import Owner
from server.apps.parties.models import Party, PartyLink


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
    # Dedup by the normalized owner slug (OpenSpec ``party-slug-minting``):
    # the slug is a minted short public identifier, minted once on
    # creation; re-merges resolve through the key. Owner slugs are
    # already normalized, so ``normalize_key`` is the identity here.
    party, party_created = Party.objects.get_or_create(
        dedup_key=Party.normalize_key(owner.slug),
        defaults={"name": owner.name or owner.slug, "i18n": i18n},
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
