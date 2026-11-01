import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, override

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser


# NOT registered with django_admin_runner on purpose: this command
# regenerates files inside the repo checkout (assets/) and only makes
# sense run manually on a developer machine when the icon pack changes —
# in a deployed container its output would be lost with the container.
class Command(BaseCommand):
    help = (
        "Regenerate category assets from the iconpacks source of truth. "
        "Copies iconpacks/<pack>/icons (resolving primitive links), runs the "
        "svgo optimize pipeline (category_optimize_svgs) and replaces "
        "server/apps/categories/assets/<pack>/."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--pack",
            type=str,
            default=None,
            help="Pack id (iconpacks/ subdirectory). Default: every pack.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing files.",
        )

    def _resolve(
        self, icons: dict[str, Any], slug: str, variant: str
    ) -> tuple[str, str] | None:
        """Follow variant links to the authored (icon, variant) pair."""
        seen: set[str] = set()
        current = (slug, variant)
        while True:
            key = f"{current[0]}#{current[1]}"
            if key in seen:
                return None  # link cycle
            seen.add(key)
            definition = icons.get(current[0], {}).get("variants", {}).get(current[1])
            if definition is None:
                return None
            if "link" in definition:
                icon_id, _, variant_id = definition["link"].partition("#")
                current = (icon_id, variant_id or variant)
                continue
            return current

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        base = Path("iconpacks")
        assets_root = Path("server/apps/categories/assets")
        pack_id = options.get("pack")
        dry_run = options.get("dry_run", False)

        pack_ids = (
            [pack_id]
            if pack_id
            else sorted(p.name for p in base.iterdir() if (p / "pack.json").is_file())
        )

        for pid in pack_ids:
            pack_dir = base / pid
            try:
                pack = json.loads((pack_dir / "pack.json").read_text())
            except (OSError, json.JSONDecodeError) as e:
                raise CommandError(
                    f"Failed to read pack manifest {pack_dir / 'pack.json'}: {e}"
                ) from e
            icons = pack["icons"]

            with tempfile.TemporaryDirectory() as tmp:
                stage = Path(tmp) / "src"
                wanted: dict[Path, Path] = {}  # staged -> dest asset
                for slug, icon in sorted(icons.items()):
                    for variant in icon.get("variants", {}):
                        resolved = self._resolve(icons, slug, variant)
                        if resolved is None:
                            continue
                        src = pack_dir / "icons" / resolved[0] / f"{resolved[1]}.svg"
                        if not src.is_file():
                            self.stdout.write(
                                self.style.WARNING(
                                    f"skip {pid}/{slug}#{variant}: no file at {src}"
                                )
                            )
                            continue
                        dst_stage = stage / pid / variant / f"{slug}.svg"
                        dst_stage.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst_stage)
                        wanted[dst_stage] = assets_root / pid / variant / f"{slug}.svg"

                if not wanted:
                    self.stdout.write(self.style.WARNING(f"{pid}: nothing to sync"))
                    continue

                out = Path(tmp) / "out"
                if dry_run:
                    for _, dest in sorted(wanted.items()):
                        state = (
                            "=" if dest.is_file() and dest.read_bytes() != b"" else "+"
                        )
                        self.stdout.write(f"{'=' if state == '=' else '+'} {dest}")
                    continue

                call_command("category_optimize_svgs", str(stage), "-o", str(out))

                replaced = 0
                for staged, dest in sorted(wanted.items()):
                    produced = out / staged.relative_to(stage)
                    if not produced.is_file():
                        self.stdout.write(
                            self.style.WARNING(
                                f"svgo produced no output for {staged.name}"
                            )
                        )
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(produced, dest)
                    replaced += 1

                # drop stale assets this pack no longer defines
                removed = 0
                for dest in sorted(
                    p
                    for p in (assets_root / pid).glob("*/*.svg")
                    if p not in wanted.values()
                ):
                    dest.unlink()
                    removed += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"{pid}: {replaced} assets updated"
                        + (f", {removed} stale removed" if removed else "")
                    )
                )
