"""martin_sync config generation: the MLT conversion opt-in survives.

`convert_to_mlt` lives in the authored template
(``tile_server/config/martin.yaml``); ``martin_sync`` regenerates the
deployed config through ``yaml.safe_load`` → mutate sprites →
``yaml.dump``. These tests pin that the per-source opt-in arrives in the
generated file unchanged — a failure would surface at deploy time
(config lost) instead of serve time (no MLT for ``.mlt`` URLs).
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest.mock
from pathlib import Path
from typing import Any, override

import yaml

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from server.apps.envvars.models import EnvVar
from server.apps.envvars.registry import CACHE_KEY
from server.apps.huts.management.commands.martin_sync import (
    Command,
    resolve_passthrough_headers,
)

TEMPLATE = Path(settings.BASE_DIR) / "tile_server" / "config" / "martin.yaml"


def _generated_config(tmp: Path) -> dict[str, Any]:
    """Run the config-generation step into ``tmp`` and load the result."""
    out, err = io.StringIO(), io.StringIO()
    command = Command(stdout=out, stderr=err)
    # Same shape the command's handle() initializes (counters it bumps
    # on write; only config generation runs — no DB steps involved).
    stats: dict[str, Any] = {
        "files_copied": 0,
        "files_updated": 0,
        "files_created": 0,
        "bytes_copied": 0,
        "files_skipped": 0,
        "categories_processed": 0,
        "categories_skipped": 0,
        "errors": 0,
        "config_changed": False,
        "files_deleted": 0,
        "sprite_dirs": [],
    }
    command._sync_config(tmp, dry_run=False, stats=stats)
    generated = tmp / "config" / "martin.yaml"
    assert generated.exists(), err.getvalue() or "config not generated"
    with open(generated) as f:
        return yaml.safe_load(f)


class MartinSyncMltConfigTests(SimpleTestCase):
    def test_template_has_huts_conversion_opt_in(self):
        # Guard: the opt-in must not silently disappear from the template
        with open(TEMPLATE) as f:
            template = yaml.safe_load(f)
        self.assertEqual(
            template["postgres"]["tables"]["huts"].get("convert_to_mlt"),
            "auto",
        )

    def test_conversion_opt_in_survives_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated = _generated_config(Path(tmp))
        self.assertEqual(
            generated["postgres"]["tables"]["huts"].get("convert_to_mlt"),
            "auto",
        )


class ResolvePassthroughHeadersTests(TestCase):
    """``resolve_passthrough_headers`` — the DB→config API-key bridge.

    The env registry's precedence rules reach the GENERATED martin.yaml
    through exactly this function; each edge (shorthand sources,
    registry misses, ``${NAME:-default}`` forms, env fallback) is the
    difference between an authenticated and a 401-ing upstream.
    """

    @override
    def setUp(self) -> None:
        # Fresh registry snapshot per test (row saves invalidate via
        # signals; explicit delete mirrors tests/apps/envvars).
        EnvVar.objects.filter(name="TRANSITLAND_API_KEY").delete()
        cache.delete(CACHE_KEY)

    @override
    def tearDown(self) -> None:
        cache.delete(CACHE_KEY)

    def _config(self) -> dict[str, Any]:
        return {
            "postgres": {"connection_string": "$DATABASE_URL"},
            "passthrough": {
                "sources": {
                    # detailed source with an auth header (the real
                    # transitland_stops shape)
                    "transitland_stops": {
                        "url": "https://transit.land/api/v2/tiles/{z}/{x}/{y}.pbf",
                        "headers": {"apikey": "${TRANSITLAND_API_KEY:-}"},
                    },
                    # shorthand URL source — no headers to resolve
                    "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                }
            },
        }

    def test_registry_value_substituted_into_header(self):
        EnvVar.objects.update_or_create(
            name="TRANSITLAND_API_KEY",
            defaults={"value": "secret-key", "is_active": True},
        )
        config = self._config()
        resolved = resolve_passthrough_headers(config)
        headers = config["passthrough"]["sources"]["transitland_stops"]["headers"]
        self.assertEqual(headers["apikey"], "secret-key")
        self.assertEqual(resolved, ["TRANSITLAND_API_KEY"])

    def test_default_suffix_token_fully_consumed(self):
        """`${NAME:-fallback}` — the whole token including the default
        is replaced, not just the bare name."""
        EnvVar.objects.update_or_create(
            name="TRANSITLAND_API_KEY",
            defaults={"value": "secret-key", "is_active": True},
        )
        config = self._config()
        config["passthrough"]["sources"]["transitland_stops"]["headers"]["apikey"] = (
            "${TRANSITLAND_API_KEY:-literal-default}"
        )
        resolve_passthrough_headers(config)
        headers = config["passthrough"]["sources"]["transitland_stops"]["headers"]
        self.assertEqual(headers["apikey"], "secret-key")

    def test_registry_miss_leaves_token_verbatim(self):
        """No row, no env var: the token survives for Martin's own env
        expansion (``:-`` default degrades to empty = unauthenticated
        upstream, never a broken config)."""
        # Guard against a wrapper-injected export (infisical run) so the
        # miss case is deterministic regardless of the host environment.
        with unittest.mock.patch.dict(os.environ):
            os.environ.pop("TRANSITLAND_API_KEY", None)
            config = self._config()
            resolved = resolve_passthrough_headers(config)
        headers = config["passthrough"]["sources"]["transitland_stops"]["headers"]
        self.assertEqual(headers["apikey"], "${TRANSITLAND_API_KEY:-}")
        self.assertEqual(resolved, [])

    def test_env_fallback_resolves_when_row_empty(self):
        """Empty DB value + env_fallback=True resolves from the process
        environment (the registry's documented precedence)."""
        EnvVar.objects.update_or_create(
            name="TRANSITLAND_API_KEY",
            defaults={"value": "", "is_active": True, "env_fallback": True},
        )
        with unittest.mock.patch.dict(os.environ, {"TRANSITLAND_API_KEY": "from-env"}):
            config = self._config()
            resolve_passthrough_headers(config)
        headers = config["passthrough"]["sources"]["transitland_stops"]["headers"]
        self.assertEqual(headers["apikey"], "from-env")

    def test_scoped_to_passthrough_headers_only(self):
        """Other `${…}` tokens (DATABASE_URL, sprite-path defaults) keep
        Martin's own env expansion — the registry is an API-key
        allowlist, not a substitution engine."""
        EnvVar.objects.update_or_create(
            name="DATABASE_URL",
            defaults={"value": "postgres://injected", "is_active": True},
        )
        config = self._config()
        config["sprites"] = {
            "paths": ["${MARTIN_SYNC_MOUNT:-/martin_sync}/sprites/transport"]
        }
        resolve_passthrough_headers(config)
        self.assertEqual(
            config["postgres"]["connection_string"],
            "$DATABASE_URL",  # single-$ form untouched (not a token)
        )
        self.assertEqual(
            config["sprites"]["paths"][0],
            "${MARTIN_SYNC_MOUNT:-/martin_sync}/sprites/transport",
        )

    def test_shorthand_source_without_headers_is_skipped(self):
        """String/list source values (shorthand form) carry no headers —
        the walk must not raise on them."""
        config = {
            "passthrough": {
                "sources": {
                    "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                    "mirrors": [
                        "https://a.example.org/{z}/{x}/{y}.png",
                        "https://b.example.org/{z}/{x}/{y}.png",
                    ],
                }
            }
        }
        self.assertEqual(resolve_passthrough_headers(config), [])
