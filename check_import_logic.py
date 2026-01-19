#!/usr/bin/env python3
"""
Script to validate MeteoSwiss import logic without database
"""

import json
from pathlib import Path

# Load the mapping and descriptions
base_path = Path("server/apps/meteo/assets")
mapping_file = base_path / "meteoswiss/wmo4677mapping.json"
descriptions_file = base_path / "wmo_descriptions.json"

with open(mapping_file, "r") as f:
    wmo_mappings = json.load(f)

with open(descriptions_file, "r") as f:
    wmo_descriptions = json.load(f)

# Build the wmo_code_mappings structure (same logic as import script)
wmo_code_mappings = {}

for icon_id, mapping in wmo_mappings.items():
    wmo_codes = mapping.get("wmo_codes", [mapping.get("wmo_code")])
    if not isinstance(wmo_codes, list):
        wmo_codes = [wmo_codes]

    priority = mapping["priority"]
    is_day = mapping.get("is_day", True)

    for wmo_code in wmo_codes:
        if wmo_code not in wmo_code_mappings:
            wmo_code_mappings[wmo_code] = {"day": [], "night": []}

        period = "day" if is_day else "night"
        wmo_code_mappings[wmo_code][period].append((icon_id, priority))

# Show results
print(f"\n{'='*80}")
print("WMO Code Coverage Analysis")
print(f"{'='*80}\n")

# Check coverage
covered_codes = sorted(wmo_code_mappings.keys())
print(f"Total WMO codes covered: {len(covered_codes)}")
print(f"Covered codes: {covered_codes}\n")

# Check for forecast codes (0-3, 45-99)
forecast_codes = set(range(0, 4)) | set(range(45, 100))
covered_forecast = forecast_codes & set(covered_codes)
missing_forecast = forecast_codes - set(covered_codes)

print(f"Forecast codes covered: {len(covered_forecast)}/59")
if missing_forecast:
    print(f"Missing forecast codes: {sorted(missing_forecast)}")
else:
    print("✓ All forecast codes covered!")

print(f"\n{'='*80}")
print("Day/Night Symbol Assignments")
print(f"{'='*80}\n")

# Check a few sample codes to show day/night logic
sample_codes = [0, 1, 2, 3, 61, 95, 96, 97]

for wmo_code in sample_codes:
    if wmo_code not in wmo_code_mappings:
        print(f"WMO {wmo_code:3d}: NOT COVERED")
        continue

    periods = wmo_code_mappings[wmo_code]

    # Get highest priority icons
    day_icons = sorted(periods.get("day", []), key=lambda x: x[1], reverse=True)
    night_icons = sorted(periods.get("night", []), key=lambda x: x[1], reverse=True)

    best_day = day_icons[0] if day_icons else None
    best_night = night_icons[0] if night_icons else None

    # Get descriptions
    desc_data = wmo_descriptions.get(str(wmo_code), {})
    desc_day = desc_data.get("en", "N/A")
    desc_night = desc_data.get("en_night", "N/A")

    print(f"WMO {wmo_code:3d}:")
    if best_day:
        print(
            f"  Day:   Icon {best_day[0]:>3s} (priority {best_day[1]:3d}) - {desc_day}"
        )
    else:
        print(f"  Day:   NO ICON - {desc_day}")

    if best_night:
        print(
            f"  Night: Icon {best_night[0]:>3s} (priority {best_night[1]:3d}) - {desc_night}"
        )
    else:
        print(f"  Night: NO ICON - {desc_night}")
    print()

print(f"{'='*80}")
print("Icon Usage Statistics")
print(f"{'='*80}\n")

# Count how many WMO codes each icon covers
icon_usage = {}
for icon_id, mapping in wmo_mappings.items():
    wmo_codes = mapping.get("wmo_codes", [mapping.get("wmo_code")])
    if not isinstance(wmo_codes, list):
        wmo_codes = [wmo_codes]
    icon_usage[icon_id] = len(wmo_codes)

day_icons = [k for k in wmo_mappings.keys() if wmo_mappings[k].get("is_day", True)]
night_icons = [
    k for k in wmo_mappings.keys() if not wmo_mappings[k].get("is_day", True)
]

print(f"Total unique icons: {len(wmo_mappings)}")
print(f"Day icons: {len(day_icons)}")
print(f"Night icons: {len(night_icons)}")
print("\nTop 5 icons by WMO code coverage:")
for icon_id, count in sorted(icon_usage.items(), key=lambda x: x[1], reverse=True)[:5]:
    is_day = wmo_mappings[icon_id].get("is_day", True)
    period = "day" if is_day else "night"
    print(f"  Icon {icon_id:>3s} ({period:>5s}): covers {count:2d} WMO codes")
