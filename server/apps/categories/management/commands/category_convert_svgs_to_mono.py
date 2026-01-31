import re
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Convert SVG files to mono (black) by replacing all colors/strokes with black"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "source_dir",
            type=str,
            help="Path to source SVG files to convert",
        )
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            help="Path to output directory (default: source_dir/mono)",
        )

    def convert_svg_to_mono(self, svg_content):
        """
        Convert SVG to mono by replacing all colors with black.

        This function:
        1. Replaces fill colors with black (#000000 or currentColor)
        2. Replaces stroke colors with black
        3. Removes unnecessary attributes
        4. Simplifies the SVG by removing gradients, shadows, styles, etc.
        """
        # Remove style tags completely
        svg_content = re.sub(
            r"<style[^>]*>.*?</style>", "", svg_content, flags=re.DOTALL | re.IGNORECASE
        )

        # Remove gradients definitions
        svg_content = re.sub(r"<defs>.*?</defs>", "", svg_content, flags=re.DOTALL)

        # Remove Inkscape/sodipodi namedview (self-closing or with closing tag)
        svg_content = re.sub(
            r"<sodipodi:namedview[^>]*/>", "", svg_content, flags=re.DOTALL
        )
        svg_content = re.sub(
            r"<sodipodi:namedview[^>]*>.*?</sodipodi:namedview>",
            "",
            svg_content,
            flags=re.DOTALL,
        )

        # Remove Inkscape/sodipodi attributes from svg tag
        svg_content = re.sub(r' xmlns:inkscape="[^"]*"', "", svg_content)
        svg_content = re.sub(r' xmlns:sodipodi="[^"]*"', "", svg_content)
        svg_content = re.sub(r' inkscape:[^=]*="[^"]*"', "", svg_content)
        svg_content = re.sub(r' sodipodi:[^=]*="[^"]*"', "", svg_content)
        svg_content = re.sub(r' id="[^"]*"', "", svg_content)

        # Remove sodipodi guide elements
        svg_content = re.sub(r"<sodipodi:guide[^>]*/>", "", svg_content)

        # Replace all color values with black or currentColor
        # Hex colors
        svg_content = re.sub(
            r'fill="#[0-9a-fA-F]{6}"', 'fill="currentColor"', svg_content
        )
        svg_content = re.sub(
            r'stroke="#[0-9a-fA-F]{6}"', 'stroke="currentColor"', svg_content
        )

        # RGB colors
        svg_content = re.sub(r'fill="rgb\([^)]+\)"', 'fill="currentColor"', svg_content)
        svg_content = re.sub(
            r'stroke="rgb\([^)]+\)"', 'stroke="currentColor"', svg_content
        )

        # RGBA colors
        svg_content = re.sub(
            r'fill="rgba\([^)]+\)"', 'fill="currentColor"', svg_content
        )
        svg_content = re.sub(
            r'stroke="rgba\([^)]+\)"', 'stroke="currentColor"', svg_content
        )

        # Named colors (common ones)
        color_names = [
            "white",
            "black",
            "red",
            "green",
            "blue",
            "yellow",
            "orange",
            "purple",
            "pink",
            "brown",
            "gray",
            "grey",
            "cyan",
            "magenta",
        ]
        for color in color_names:
            svg_content = re.sub(
                f'fill="{color}"',
                'fill="currentColor"',
                svg_content,
                flags=re.IGNORECASE,
            )
            svg_content = re.sub(
                f'stroke="{color}"',
                'stroke="currentColor"',
                svg_content,
                flags=re.IGNORECASE,
            )

        # Remove opacity attributes
        svg_content = re.sub(r' opacity="[0-9.]+"', "", svg_content)
        svg_content = re.sub(r' fill-opacity="[0-9.]+"', "", svg_content)
        svg_content = re.sub(r' stroke-opacity="[0-9.]+"', "", svg_content)

        # Remove filter references
        svg_content = re.sub(r' filter="[^"]*"', "", svg_content)

        # Remove style attributes that might contain colors
        def remove_colors_from_style(match):
            style = match.group(1)
            # Remove color-related CSS properties
            style = re.sub(r"fill:\s*[^;]+;?", "", style)
            style = re.sub(r"stroke:\s*[^;]+;?", "", style)
            style = re.sub(r"color:\s*[^;]+;?", "", style)
            style = re.sub(r"opacity:\s*[^;]+;?", "", style)
            # Clean up trailing semicolons and whitespace
            style = re.sub(r";\s*$", "", style)
            style = style.strip()
            return f' style="{style}"' if style else ""

        svg_content = re.sub(r' style="([^"]*)"', remove_colors_from_style, svg_content)

        return svg_content

    def handle(self, *args, **options):
        source_path = Path(options["source_dir"])

        if not source_path.exists():
            self.stdout.write(
                self.style.ERROR(f"Source directory not found: {source_path}")
            )
            return

        # Determine output directory
        if options.get("output"):
            output_path = Path(options["output"])
        else:
            output_path = source_path.parent / "mono"

        # Create output directory
        output_path.mkdir(parents=True, exist_ok=True)

        self.stdout.write(f"Source: {source_path}")
        self.stdout.write(f"Output: {output_path}")
        self.stdout.write("")

        # Find all SVG files
        svg_files = list(source_path.glob("*.svg"))

        if not svg_files:
            self.stdout.write(
                self.style.WARNING("No SVG files found in source directory!")
            )
            return

        self.stdout.write(f"Found {len(svg_files)} SVG files to convert")
        self.stdout.write("")

        # Convert each file
        converted_count = 0
        for svg_file in svg_files:
            try:
                # Read source file
                with open(svg_file, "r") as f:
                    content = f.read()

                # Convert to mono
                mono_content = self.convert_svg_to_mono(content)

                # Write to output
                output_file = output_path / svg_file.name
                with open(output_file, "w") as f:
                    f.write(mono_content)

                self.stdout.write(f"✓ Converted: {svg_file.name}")
                converted_count += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"✗ Failed to convert {svg_file.name}: {e}")
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully converted {converted_count}/{len(svg_files)} files"
            )
        )
