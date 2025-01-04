import re


def guess_hut_type(
    name: str = "",
    capacity: int | None = 0,
    capacity_shelter: int | None = 0,
    elevation: float | None = 1500,
    organization: str | None = "",
    osm_tag: str | None = "",
    # ) -> HutType:
) -> str:
    if name is None:
        name = ""
    if capacity is None:
        capacity = 0
    if capacity_shelter is None:
        capacity_shelter = 0
    if elevation is None:
        elevation = 1500
    if organization is None:
        organization = ""
    if osm_tag is None:
        osm_tag = ""

    def _in(patterns: list, target: str):
        for pat in patterns:
            if re.search(pat.lower(), target.lower()):
                # rprint(f"Match {pat} in '{target}'")
                return True
        return False

    name = name.lower()
    _hut_names = [
        r"huette",
        r"h[iü]tt[ae]",
        r"camona",
        r"capanna",
        r"cabane",
        r"huisli",
    ]
    _bivi_names = [r"r[ie]fug[ei]", r"biwak", r"bivouac", r"bivacco"]
    _basic_hotel_names = [
        r"berghotel",
        r"berggasthaus",
        r"auberge",
        r"gasthaus",
        r"berghaus",
    ]
    _camping_names = [r"camping", r"zelt"]
    _hotel_names = [r"h[oô]tel"]
    _hostel_names = [r"hostel", r"jugendherberg"]
    _restaurant_names = [r"restaurant", r"ristorante", r"beizli"]
    _possible_hut = _in(_hut_names, name)
    _slug = "unknown"
    if _in(_basic_hotel_names, name):
        _slug = "basic-hotel"
    elif _in(_hotel_names, name):
        _slug = "hotel"
    elif _in(_hostel_names, name):
        _slug = "hostel"
    elif _in(_restaurant_names, name):
        _slug = "restaurant"
    elif _in(_camping_names, name):
        _slug = "camping"
    elif osm_tag == "wilderness_hut":
        if elevation > 2500 and not _possible_hut:
            _slug = "bivouac"
        # if _possible_hut:
        # _type = HutType.unattended_hut
        else:
            _slug = "basic-shelter"
    elif (capacity == capacity_shelter or capacity < 22) and capacity > 0:
        if elevation > 2500 and not _possible_hut:
            _slug = "bivouac"
        else:
            _slug = "unattended-hut"
    elif _possible_hut:
        _slug = "hut"
    elif _in(_bivi_names, name):
        _slug = "bivouac"
    elif _in(["alp", "alm", "hof"], name) and elevation < 2000:
        _slug = "alp"
    elif organization in ["sac", "dav"] or osm_tag == "alpine_hut":
        _slug = "hut"
    return _slug
    # _type, _created = HutType.objects.get_or_create(slug=_slug)
    # return _type
