# MeteoSwiss Import - Implementation Summary

## Changes Made

### 1. Slug Mapping (models.py)
- Changed WMO code 0 from `"sunny"` to `"clear"` (more generic, works for both day/night)
- Changed WMO code 1 from `"mostly-sunny"` to `"mostly-clear"`

### 2. Import Script (import_meteoswiss.py)
Completely restructured to properly handle day/night symbols:

#### Previous Approach (INCORRECT):
- One WeatherCode entry per icon_id
- Same symbol for both day and night
- Used descriptions from mapping JSON (not complete)
- Created 162 WeatherCode entries (84 icons × ~2 WMO codes each)

#### New Approach (CORRECT):
- **One WeatherCode entry per WMO code** (source_id = WMO code)
- **Separate day and night symbols**
- **Uses wmo_descriptions.json for complete day/night descriptions**
- Creates 59 WeatherCode entries (one per forecast code)

### 3. Day/Night Symbol Logic

#### Icon ID Structure:
- Day icons: 1-42
- Night icons: 101-142 (night = day + 100)

#### Processing Logic:
1. Group all icons by their WMO codes
2. Separate into day and night lists
3. Select highest priority icon for each period
4. Assign to symbol_day and symbol_night fields

#### Example - WMO Code 0 (Clear):
```
Day:   Icon 1   (priority 100) → "Sonnig" / "Sunny"
Night: Icon 101 (priority 90)  → "Klar" / "Clear"
```

### 4. Description Structure
From `wmo_descriptions.json`:
```json
{
  "0": {
    "de": "Sonnig",           // Day description
    "fr": "Ensoleillé",
    "it": "Soleggiato",
    "en": "Sunny",
    "de_night": "Klar",       // Night description
    "fr_night": "Ciel dégagé",
    "it_night": "Sereno",
    "en_night": "Clear"
  }
}
```

### 5. WeatherCode Model Fields
Each WeatherCode entry now has:
- `code`: WMO code (0-99)
- `slug`: Auto-generated friendly slug (e.g., "clear", "rain-light")
- `priority`: Highest priority from all mapped icons
- `description_day`: Day description (main language)
- `description_night`: Night description (main language)
- `description_day_de/fr/it`: Day translations (via i18n)
- `description_night_de/fr/it`: Night translations (via i18n)
- `symbol_day`: Best day icon (highest priority)
- `symbol_night`: Best night icon (highest priority)
- `source_id`: WMO code as string (for unique constraint)

## Coverage Results

### Complete Coverage
✅ All 59 forecast-relevant WMO codes (0-3, 45-99)
✅ Including previously missing codes: 96, 97

### Icon Distribution
- 84 unique MeteoSwiss icons (42 day + 42 night)
- Icon 14/114 covers most codes (11 WMO codes each - drizzle/rain variants)
- Each WMO code gets best matching icons based on priority

### Example Mappings

| WMO | Description | Day Icon | Night Icon |
|-----|-------------|----------|------------|
| 0 | Clear/Sunny | 1 (prio 100) | 101 (prio 90) |
| 1 | Mostly clear | 2 (prio 100) | 102 (prio 90) |
| 61 | Light rain | 14 (prio 100) | 114 (prio 90) |
| 95 | Thunderstorm | 24 (prio 100) | 112 (prio 40) |
| 96 | Thunderstorm w/ light hail | 24 (prio 100) | 124 (prio 25) |
| 97 | Heavy thunderstorm | 24 (prio 100) | 124 (prio 25) |

## Usage

### Reset existing data (optional):
```bash
python manage.py reset_weather_data --org meteoswiss --confirm
```

### Import MeteoSwiss data:
```bash
# Download icons and import codes
python manage.py import_meteoswiss

# Skip download if icons exist
python manage.py import_meteoswiss --skip-download

# Dry run to preview
python manage.py import_meteoswiss --dry-run
```

### Verify import:
```bash
python check_import_logic.py
```

## Database Structure

### Before (Old Approach):
- 162 WeatherCode entries
- Multiple entries per WMO code (one per icon)
- Same symbol for day/night
- Incomplete descriptions

### After (New Approach):
- 59 WeatherCode entries (one per forecast code)
- One entry per WMO code
- Separate day/night symbols
- Complete day/night descriptions in all languages

## Files Modified

1. `server/apps/meteo/models.py` - Updated slug mapping for codes 0 and 1
2. `server/apps/meteo/management/commands/import_meteoswiss.py` - Complete rewrite
3. `server/settings/components/unfold.py` - Added Meteo to admin navigation

## Files Created

1. `check_import_logic.py` - Validation script (can be deleted after testing)
2. `meteoswiss_import_summary.md` - This document (can be deleted)
