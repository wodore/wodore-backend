"""
Country group definitions for GeoNames import commands.

Provides named groups of countries for convenient importing.
"""

# Alpine countries - all countries that touch the Alps
ALPS_COUNTRIES = ["AT", "CH", "DE", "FR", "IT", "LI", "MC", "SI"]

# Map of group names to country lists
COUNTRY_GROUPS = {
    "alps": ALPS_COUNTRIES,
}


def expand_countries(countries_input: str) -> list[str]:
    """
    Expand country codes, resolving named groups.

    Args:
        countries_input: Comma-separated list of country codes or group names
                        (e.g., "ch,de" or "alps" or "alps,es")

    Returns:
        List of uppercase country codes

    Examples:
        >>> expand_countries("ch,de")
        ['CH', 'DE']
        >>> expand_countries("alps")
        ['AT', 'CH', 'DE', 'FR', 'IT', 'LI', 'MC', 'SI']
        >>> expand_countries("alps,es")
        ['AT', 'CH', 'DE', 'FR', 'IT', 'LI', 'MC', 'SI', 'ES']
    """
    countries = []

    for item in countries_input.split(","):
        item = item.strip().lower()

        # Check if it's a named group
        if item in COUNTRY_GROUPS:
            countries.extend(COUNTRY_GROUPS[item])
        else:
            # It's a country code
            countries.append(item.upper())

    # Remove duplicates while preserving order
    seen = set()
    result = []
    for country in countries:
        if country not in seen:
            seen.add(country)
            result.append(country)

    return result
