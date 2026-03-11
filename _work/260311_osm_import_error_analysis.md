WIP: OSM import error analysis and fixes.

- Symptoms: frequent "Category matching query does not exist" and update_fields ValueError
  for translation fields in OSM import logs.
- Root cause: brand slugs created lower/underscore while BrandInput used raw brand string,
  causing missing Category on brand lookup; translation updates used non-concrete
  modeltrans fields in update_fields, raising ValueError.
- Fixes: normalize brand slugs consistently and use brand category slug in BrandInput;
  guard brand lookups in GeoPlace; update GeoPlace i18n updates to save via "i18n"
  instead of name_xx/description_xx fields.
