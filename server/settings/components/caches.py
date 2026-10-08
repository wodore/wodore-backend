# Caching
# https://docs.djangoproject.com/en/4.2/topics/cache/

from decouple import config

CACHES = {
    "default": {
        # TODO: use some other cache in production,
        # like https://github.com/jazzband/django-redis
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "TIMEOUT": 300,  # 5 minutes default for short-term cache
        "OPTIONS": {
            "MAX_ENTRIES": 1000,
        },
    },
    "persistent": {
        # Database cache for long-term data (images, metadata, providers, licenses)
        # Data persists across restarts and deployments
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache_persistent",
        "TIMEOUT": None,  # No default expiration (indefinite)
        "OPTIONS": {
            "MAX_ENTRIES": 100000,  # 100k entries - supports ~30k locations with 3 providers each
            "CULL_FREQUENCY": 4,  # Remove 25% of oldest entries when full
        },
    },
    # hut-services library cache (see server/core/apps.py: ready() injects this
    # alias as the lib's cache backend via set_default_cache_backend).
    # Database backend so external-service responses survive restarts and are
    # shared across workers - the lib's own default would write pickles to
    # <tempdir>/py_file_cache. Dedicated alias/table so the lib's clear_cache()
    # cannot evict other apps' entries. The table is created by the no-args
    # `manage.py createcachetable` (and automatically on test databases).
    "hut_services": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache_hut_services",
        "TIMEOUT": 172800,  # 2 days - mirrors the lib's HUT_SERVICE_EXPIRE_SECONDS default
        "OPTIONS": {
            "MAX_ENTRIES": 100000,
            "CULL_FREQUENCY": 4,  # Evict 25% when full, same policy as "persistent"
        },
    },
    "shared": {
        # Cross-process cache for django-q2 cluster status (sentinel and
        # worker stats). LocMem is per-process: without a shared backend
        # the web/admin process can never see the running qcluster.
        # The table is created by `manage.py createcachetable` (the no-args
        # form creates a table for every DatabaseCache alias).
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache_shared",
        "TIMEOUT": 3600,
        "OPTIONS": {
            "MAX_ENTRIES": 1000,
        },
    },
    # Throttle counters (openspec: api-throttling). LocMem default is
    # correct for dev/test (single process); production.py overrides to
    # DatabaseCache — rate limits must hold across workers.
    "throttling": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "TIMEOUT": 3600,
        "OPTIONS": {
            "MAX_ENTRIES": 10000,
        },
    },
}


# django-axes
# https://django-axes.readthedocs.io/en/latest/4_configuration.html#configuring-caches

AXES_CACHE = "default"

# Geo-images endpoint response cache (see server/apps/geometries/image_response_cache.py).
# Fresh window = served directly; after that a stored response is only used as
# stale fallback when recomputation fails. Storage TTL bounds the fallback.
IMAGE_RESPONSE_CACHE_FRESH_SECONDS = config(
    "IMAGE_RESPONSE_CACHE_FRESH_SECONDS", cast=int, default=15 * 60
)
IMAGE_RESPONSE_CACHE_STALE_SECONDS = config(
    "IMAGE_RESPONSE_CACHE_STALE_SECONDS", cast=int, default=7 * 24 * 3600
)
