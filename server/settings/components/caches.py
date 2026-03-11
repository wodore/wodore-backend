# Caching
# https://docs.djangoproject.com/en/4.2/topics/cache/

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
}


# django-axes
# https://django-axes.readthedocs.io/en/latest/4_configuration.html#configuring-caches

AXES_CACHE = "default"
