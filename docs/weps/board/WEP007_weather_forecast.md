---
draft: false
date:
  created: 2026-01-18
  updated: 2026-01-18
slug: wep007
categories:
  - WEP
  - Weather
tags:
  - wep007
  - weather
---

# `WEP 7` Weather Forecast

Weather forecast integration for huts and mountain locations.
<!-- more -->

## Overview

**Basic Concept:**

* Display **14-day weather forecast** per hut
* Frontend-driven display (direct API calls from client)
* Store daily weather data in DB (similar to availability data)
* Enable weather-based hut search: "Show huts with good weather this weekend" or "Huts with temperature > 20°C"
* Group nearby hut locations to reduce API calls
* Daily updates via background job

## Use Cases

**Phase 1: Display (Frontend-only)**

* Show 14-day forecast on hut detail pages
* Link to detailed national weather service based on country

**Phase 2: Search & Filtering (Backend storage)**

* "Show me all huts with good weather this weekend"
* "Find huts with temperature over 20°C on Saturday"
* "Huts with less than 20% precipitation probability"
* Filter by snow conditions, wind speed, etc.

## Weather Data APIs

### Open-Meteo

**Free, open-source weather API aggregating multiple national weather services.**

* **License**: Free for non-commercial use (no API key required)
* **Rate Limits**: 10,000 requests/day
* **Resolution**: 1-11 km depending on region
* **Forecast**: Up to 16 days
* **Alpine Features**: Elevation-adjusted, snow depth, freezing level, high-altitude wind
* **Data Sources**: NOAA, DWD, Meteo-France, ECMWF, GFS, ICON
* **CORS**: Enabled (direct frontend access possible)

**Link**: [https://open-meteo.com/](https://open-meteo.com/)

**API Endpoint**: `https://api.open-meteo.com/v1/forecast`

### OpenWeatherMap

**Popular commercial weather API with free tier.**

* **License**: Free tier available
* **Rate Limits**: 60 calls/minute, 1,000,000 calls/month (free tier)
* **Forecast**: 5 days / 3-hour intervals (free), 16 days (paid)
* **Features**: Current weather, air pollution API, weather maps
* **API Key**: Required

**Link**: [https://openweathermap.org/](https://openweathermap.org/)

**API Endpoint**: `https://api.openweathermap.org/data/2.5/forecast`

### MeteoSwiss (Switzerland)

**Official Swiss weather service with open data.**

* **License**: Free, open government data
* **Coverage**: Switzerland only
* **Forecast**: Local forecasts for Swiss locations
* **Quality**: High accuracy for Alpine regions
* **API**: JSON REST API

**Links:**

* API Documentation: [https://opendatadocs.meteoswiss.ch/e-forecast-data/e4-local-forecast-data](https://opendatadocs.meteoswiss.ch/e-forecast-data/e4-local-forecast-data)
* Weather Symbols: [https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/weather-symbols.html](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/weather-symbols.html)

## Weather Icons & Code Mappings

### Basmilius Weather Icons

**Animated SVG weather icons with modern design.**

* **License**: MIT (free for commercial use)
* **Variants**: Animated, static, day/night, fill/outline
* **Quality**: High-quality, professional design

**Link**: [https://github.com/basmilius/weather-icons](https://github.com/basmilius/weather-icons)
**WMO Conversion**: [https://github.com/thielj/weather-icons](https://github.com/thielj/weather-icons)

### OMWeather Icons

**Simple, open-source weather icons with WMO code mapping.**

* **License**: Open source
* **WMO Codes**: Visual reference for all WMO weather codes
* **Coverage**: Complete WMO 4677 standard

**Links:**

* Repository: [https://github.com/woheller69/omweather/tree/master](https://github.com/woheller69/omweather/tree/master)
* WMO Code Reference Image: [https://github.com/woheller69/omweather/blob/master/wmo_codes.png](https://github.com/woheller69/omweather/blob/master/wmo_codes.png)

### WMO to OpenWeatherMap Mapping

**Code conversion between WMO 4677 and OpenWeatherMap codes.**

**Link**: [https://gist.github.com/stellasphere/9490c195ed2b53c707087c8c2db4ec0c](https://gist.github.com/stellasphere/9490c195ed2b53c707087c8c2db4ec0c)

### MeteoSwiss Icons

**Official Swiss weather service icons.**

* **License**: Unknown (check MeteoSwiss terms)
* **Coverage**: Swiss-specific weather symbols
* **Format**: SVG

**Link:** <https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/weather-symbols.html>
**Link**: [https://docs.discover.swiss/dev/reference/weather-icons/](https://docs.discover.swiss/dev/reference/weather-icons/)
**URL**: `https://www.meteoswiss.admin.ch/static/resources/weather-symbols/{id}.svg`

## Country-Specific Weather Services

### Strategy

Display broad overview in-app with link to detailed national weather service:

* **Switzerland**: Link to MeteoSwiss
* **Austria**: Link to ZAMG (Zentralanstalt für Meteorologie und Geodynamik)
* **France**: Link to Météo-France
* **Italy**: Link to Meteo.it
* **Germany**: Link to DWD (Deutscher Wetterdienst)
* **Other**: Link to MeteoBlue or Open-Meteo

### National Weather Service Links

| Country | Service | URL |
|---------|---------|-----|
| Switzerland | MeteoSwiss | `https://www.meteoswiss.admin.ch/` |
| Austria | ZAMG | `https://www.zamg.ac.at/` |
| France | Météo-France | `https://meteofrance.com/` |
| Italy | Meteo.it | `https://www.meteo.it/` |
| Germany | DWD | `https://www.dwd.de/` |
| Generic | MeteoBlue | `https://www.meteoblue.com/` |

## WMO Weather Codes (WMO 4677)

**Standard weather codes used by Open-Meteo and many national services:**

| Code | Description |
|------|-------------|
| 0 | Clear sky |
| 1, 2, 3 | Mainly clear, partly cloudy, overcast |
| 45, 48 | Fog and depositing rime fog |
| 51, 53, 55 | Drizzle: Light, moderate, dense |
| 56, 57 | Freezing drizzle: Light, dense |
| 61, 63, 65 | Rain: Slight, moderate, heavy |
| 66, 67 | Freezing rain: Light, heavy |
| 71, 73, 75 | Snow fall: Slight, moderate, heavy |
| 77 | Snow grains |
| 80, 81, 82 | Rain showers: Slight, moderate, violent |
| 85, 86 | Snow showers: Slight, heavy |
| 95 | Thunderstorm: Slight or moderate |
| 96, 99 | Thunderstorm with slight/heavy hail |

## Architecture Concept

### Phase 1: Frontend Display Only

* Frontend fetches 14-day forecast directly from Open-Meteo
* Display on hut detail page
* Link to country-specific detailed forecast
* No backend storage

### Phase 2: Backend Storage for Search

**Data Model:**

```
WeatherForecast
- location_id (group nearby huts)
- date
- temperature_max
- temperature_min
- precipitation_probability
- precipitation_sum
- weather_code
- wind_speed
- snow_depth (if applicable)
```

**Daily Update Job:**

* Fetch forecast for all location clusters
* Store 14 days of daily data per location
* Link huts to nearest weather location

**Search Capabilities:**

* Filter huts by weather conditions
* Query by temperature range, precipitation, snow conditions
* Find "good weather weekends"

## Preliminary Conclusion

* **Primary API**: Open-Meteo (free, comprehensive, Alpine-optimized)
* **Icons**: Basmilius (modern design) or MeteoSwiss (more familiar to users, requires WMO code mapping)
* **National Services**: Link to MeteoSwiss (CH), ZAMG (AT), etc. for detailed forecasts
* **Phase 1**: Frontend-only 14-day display
* **Phase 2**: Backend storage for weather-based hut search

## Implementation Status

### Completed (Phase 0: Foundation)

* **WMO Weather Code System**: Full support for WMO 4677 standard (100 codes: 0-99)
  * Universal weather code definitions with multilingual descriptions (DE/FR/IT/EN)
  * Separation of weather codes from symbol collections
  * Support for both forecast codes (0-3, 45-99) and observational codes (4-44)
  * Category-based organization (clear, cloudy, rain, snow, fog, etc.)
* **Symbol Collection Management**: Flexible system for multiple icon providers
  * MeteoSwiss filled icon collection with day/night variants (84 icons)
  * Weather-icons collections: filled, outlined, outlined-mono, filled-animated, outlined-animated (236+ icons each)
  * Collection-based symbol mapping system (one WMO code → multiple collections)
  * Extensible symbol style system supporting 11 styles (detailed, simple, mono, outlined, filled, and animated variants)
* **Import Scripts**: Automated data import from multiple sources
  * MeteoSwiss icon downloader with priority-based selection
  * Weather-icons batch importer supporting all styles
  * WMO code mapping with complete translations and categories
  * Automatic verification of forecast code coverage
* **API Endpoints**: RESTful API for weather codes and symbols
  * Query by collection, category, and individual codes
  * Configurable response detail levels (no/slug/all for symbols, categories, collections)
  * SVG redirect endpoints for efficient icon delivery
  * HTTP caching with Cache-Control headers (60s dev, 7 days production)
  * Default collection: weather-icons-outlined-mono
* **Database Optimization**: Complete indexing and query optimization
  * Foreign key indexes on all relationships
  * Composite indexes for common query patterns (collection+code, code+collection)
  * Check constraints for data integrity
  * Admin interface optimized with targeted prefetch queries
  * Disabled inlines for large datasets to improve performance
