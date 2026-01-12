"""Utility functions for external_geonames app."""

from django.utils.html import format_html


def get_progress_bar(
    value: float,
    max_value: float = 100,
    color: str | None = None,
    show_text: bool = True,
    active: bool = True,
) -> str:
    """
    Generate HTML for a progress bar.

    Args:
        value: Current value (0-max_value)
        max_value: Maximum value (default: 100)
        color: Optional hex color. If None, uses gradient based on percentage
        show_text: Whether to show the percentage text
        active: Whether the bar is active (False shows gray/unknown state)

    Returns:
        HTML string for the progress bar
    """
    # Calculate percentage
    percent = (value / max_value * 100) if max_value > 0 else 0
    percent = min(100, max(0, percent))  # Clamp between 0-100

    # Determine text and color
    if not active:
        bar_color = "#333333"
        percent_text = "?"
        percent = 0
    else:
        if color:
            bar_color = color
        else:
            # Auto color gradient based on percentage
            if percent >= 80:
                bar_color = "#33ff33"  # High - green
            elif percent >= 50:
                bar_color = "#99cc33"  # Medium-high - yellow-green
            elif percent >= 25:
                bar_color = "#ffa726"  # Medium - orange
            else:
                bar_color = "#d32f2f"  # Low - red

        percent_text = f"{percent:.0f}%"

    # Build HTML
    if show_text:
        return format_html(
            '<div style="display: flex; align-items: center; gap: 8px; min-width: 120px; padding: 2px 0;">'
            '<div style="flex: 1; background: rgba(0,0,0,0.08); border-radius: 3px; height: 10px; overflow: hidden;">'
            '<div style="background: {}; height: 100%; width: {}%;"></div>'
            "</div>"
            '<span style="font-size: 11px; font-weight: 500; min-width: 35px; text-align: right; color: #4b5563;">{}</span>'
            "</div>",
            bar_color,
            percent,
            percent_text,
        )
    else:
        return format_html(
            '<div style="background: rgba(0,0,0,0.08); border-radius: 3px; height: 10px; overflow: hidden; min-width: 100px;">'
            '<div style="background: {}; height: 100%; width: {}%;"></div>'
            "</div>",
            bar_color,
            percent,
        )
