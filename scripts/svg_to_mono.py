#!/usr/bin/env python
"""Convert SVG files to monochrome by setting all colors to a single color."""

from pathlib import Path

import click
from lxml import etree


# SVG namespace
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def parse_svg_length(value: str) -> tuple[float, str | None]:
    """Parse an SVG length value into numeric value and unit.

    Args:
        value: SVG length value (e.g., "2px", "1.5", "3em").

    Returns:
        Tuple of (numeric_value, unit). Unit is None if no unit specified.
    """
    value = value.strip()
    unit = None

    # Check for units
    for suffix in ["px", "pt", "pc", "mm", "cm", "in", "em", "ex", "%"]:
        if value.endswith(suffix):
            unit = suffix
            value = value[: -len(suffix)]
            break

    try:
        return float(value), unit
    except ValueError:
        # If parsing fails, return original
        return 1.0, None


def format_svg_length(value: float, unit: str | None) -> str:
    """Format a numeric value and unit into an SVG length string.

    Args:
        value: Numeric value.
        unit: Unit suffix (e.g., "px", "em") or None.

    Returns:
        Formatted SVG length string.
    """
    if unit:
        return f"{value}{unit}"
    return str(value)


def convert_svg_to_mono(
    input_path: Path,
    output_path: Path,
    color: str,
    stroke_factor: float | None = None,
) -> None:
    """Convert an SVG file to monochrome by setting all fill and stroke attributes.

    Only replaces colors that are actually present in the SVG. If an element
    only has stroke (no fill), only the stroke color is changed.

    Args:
        input_path: Path to the input SVG file.
        output_path: Path to write the output SVG file.
        color: Color to set (e.g., "#000000", "black", "currentColor").
        stroke_factor: Multiplier for stroke-width values (e.g., 1.5 makes
            strokes 50% thicker). None means no change to stroke width.
    """
    tree = etree.parse(input_path)
    root = tree.getroot()

    # Replace only existing fill/stroke attributes
    for elem in root.iter():
        # Only replace fill if it exists and is not "none"
        if "fill" in elem.attrib:
            current_fill = elem.attrib["fill"]
            if current_fill != "none":
                elem.attrib["fill"] = color

        # Only replace stroke if it exists
        if "stroke" in elem.attrib:
            elem.attrib["stroke"] = color

        # Adjust stroke width if factor provided
        if stroke_factor is not None and "stroke-width" in elem.attrib:
            current_width = elem.attrib["stroke-width"]
            numeric_value, unit = parse_svg_length(current_width)
            new_width = numeric_value * stroke_factor
            elem.attrib["stroke-width"] = format_svg_length(new_width, unit)

        # Handle inline styles (CSS in style attribute)
        if "style" in elem.attrib:
            style = elem.attrib["style"]
            style_parts = style.split(";")
            new_style_parts = []

            for part in style_parts:
                part = part.strip()
                if not part:
                    continue

                if part.startswith("fill:"):
                    # Only replace fill if it's not "none"
                    fill_value = part.split(":", 1)[1].strip()
                    if fill_value.lower() != "none":
                        new_style_parts.append(f"fill: {color}")
                    else:
                        new_style_parts.append(part)
                elif part.startswith("stroke:"):
                    new_style_parts.append(f"stroke: {color}")
                elif stroke_factor is not None and part.startswith("stroke-width:"):
                    # Adjust stroke-width in inline styles
                    width_value = part.split(":", 1)[1].strip()
                    numeric_value, unit = parse_svg_length(width_value)
                    new_width = numeric_value * stroke_factor
                    new_style_parts.append(
                        f"stroke-width: {format_svg_length(new_width, unit)}"
                    )
                else:
                    new_style_parts.append(part)

            elem.attrib["style"] = ";".join(new_style_parts)

    tree.write(output_path, xml_declaration=True, encoding="utf-8")


@click.command()
@click.argument("input_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("output_dir", type=click.Path(path_type=Path))
@click.option(
    "-c",
    "--color",
    default="#000000",
    show_default=True,
    help="Color to set for all fill and stroke attributes.",
)
@click.option(
    "-s",
    "--stroke-factor",
    type=float,
    default=None,
    help="Multiplier for stroke-width. E.g., 1.5 makes strokes 50% thicker.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Overwrite existing output files without prompting.",
)
def svg_to_mono(
    input_dir: Path,
    output_dir: Path,
    color: str,
    stroke_factor: float | None,
    force: bool,
) -> None:
    """Convert SVG files to monochrome.

    Recursively finds all .svg files in INPUT_DIR and converts them to monochrome
    by setting all fill and stroke attributes to the specified color.
    Output files are written to OUTPUT_DIR preserving the directory structure.

    Example:
        svg-to-mono ./input-svgs ./output-svgs --color "#FF0000" --stroke-factor 1.5
    """
    # Find all SVG files
    svg_files = list(input_dir.rglob("*.svg"))

    if not svg_files:
        click.echo(f"No SVG files found in {input_dir}")
        return

    click.echo(f"Found {len(svg_files)} SVG file(s)")

    created_dirs = set()
    converted = 0
    skipped = 0

    for svg_file in svg_files:
        # Calculate relative path and output path
        rel_path = svg_file.relative_to(input_dir)
        output_file = output_dir / rel_path

        # Check if output file exists
        if output_file.exists() and not force:
            if not click.confirm(f"Overwrite {output_file}?", default=False):
                click.echo(f"Skipping {svg_file}")
                skipped += 1
                continue

        # Create output directory if needed
        output_parent = output_file.parent
        if str(output_parent) not in created_dirs:
            output_parent.mkdir(parents=True, exist_ok=True)
            created_dirs.add(str(output_parent))

        # Convert the SVG
        try:
            convert_svg_to_mono(svg_file, output_file, color, stroke_factor)
            click.echo(f"Converted: {rel_path}")
            converted += 1
        except Exception as e:
            click.echo(f"Error converting {svg_file}: {e}", err=True)

    click.echo(f"\nDone: {converted} converted, {skipped} skipped")


if __name__ == "__main__":
    svg_to_mono()
