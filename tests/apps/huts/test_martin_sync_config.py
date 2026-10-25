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
import tempfile
from pathlib import Path
from typing import Any

import yaml

from django.conf import settings
from django.test import SimpleTestCase

from server.apps.huts.management.commands.martin_sync import Command

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
