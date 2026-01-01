"""
Utility functions for availability tracking.
"""

import datetime


def parse_availability_date(
    date: datetime.date | datetime.datetime | str | None,
) -> datetime.datetime:
    """
    Parse various date formats into a normalized datetime at midnight UTC.

    This function handles multiple input formats and normalizes them to midnight UTC
    for consistent date comparisons in availability tracking.

    Args:
        date: Can be:
            - datetime.date: Will be converted to midnight UTC
            - datetime.datetime: Will be normalized to midnight UTC
            - str: Special values ("now", "weekend") or parseable date strings
            - None: Defaults to today at midnight UTC

    Returns:
        datetime.datetime: Normalized to midnight UTC for date comparison

    Raises:
        ValueError: If date string format is not recognized

    Examples:
        >>> parse_availability_date("now")
        datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)

        >>> parse_availability_date("01.06.2026")
        datetime.datetime(2026, 6, 1, 0, 0, tzinfo=datetime.timezone.utc)

        >>> parse_availability_date(datetime.date(2026, 6, 1))
        datetime.datetime(2026, 6, 1, 0, 0, tzinfo=datetime.timezone.utc)
    """
    # Parse the start date and normalize to midnight UTC for date comparison
    if isinstance(date, datetime.date) and not isinstance(date, datetime.datetime):
        start_datetime = datetime.datetime(
            date.year, date.month, date.day, tzinfo=datetime.timezone.utc
        )
    elif isinstance(date, datetime.datetime):
        # If already timezone-aware, use as-is; otherwise make it UTC
        # Normalize to midnight for proper date comparison
        dt = (
            date
            if date.tzinfo is not None
            else date.replace(tzinfo=datetime.timezone.utc)
        )
        start_datetime = datetime.datetime(
            dt.year, dt.month, dt.day, tzinfo=datetime.timezone.utc
        )
    elif isinstance(date, str) and date.lower() == "now":
        now = datetime.datetime.now(datetime.timezone.utc)
        # Normalize to midnight of today for date comparison
        start_datetime = datetime.datetime(
            now.year, now.month, now.day, tzinfo=datetime.timezone.utc
        )
    elif isinstance(date, str) and date.lower() == "weekend":
        today = datetime.datetime.now(datetime.timezone.utc)
        # Calculate next Saturday (5 = Saturday in weekday())
        days_until_weekend = (5 - today.weekday()) % 7
        weekend_date = today + datetime.timedelta(days=days_until_weekend)
        # Normalize to midnight for date comparison
        start_datetime = datetime.datetime(
            weekend_date.year,
            weekend_date.month,
            weekend_date.day,
            tzinfo=datetime.timezone.utc,
        )
    elif date is None:
        now = datetime.datetime.now(datetime.timezone.utc)
        # Normalize to midnight of today for date comparison
        start_datetime = datetime.datetime(
            now.year, now.month, now.day, tzinfo=datetime.timezone.utc
        )
    elif isinstance(date, str):
        # Try to parse string dates in various formats
        parsed_datetime = None
        for fmt in [
            "%d.%m.%Y",
            "%d.%m.%y",
            "%Y-%m-%d",
            "%y-%m-%d",
            "%Y/%m/%d",
            "%y/%m/%d",
        ]:
            try:
                parsed_datetime = datetime.datetime.strptime(date, fmt)
                break
            except ValueError:
                continue

        if parsed_datetime is None:
            msg = (
                f"Unsupported date format: {date}. "
                "Supported formats: dd.mm.yyyy, dd.mm.yy, yyyy-mm-dd, yy-mm-dd, "
                "yyyy/mm/dd, yy/mm/dd, 'now', 'weekend'"
            )
            raise ValueError(msg)

        # Normalize to midnight UTC
        start_datetime = datetime.datetime(
            parsed_datetime.year,
            parsed_datetime.month,
            parsed_datetime.day,
            tzinfo=datetime.timezone.utc,
        )
    else:
        msg = f"Unsupported date type: {type(date).__name__} for value: {date}"
        raise ValueError(msg)

    return start_datetime
