"""
Generic scoring helper functions for image providers.

Provides utilities to score images based on metadata completeness,
technical quality, and other signals.
"""

from typing import Optional


def score_metadata_completeness(
    has_description: bool = False,
    has_author: bool = False,
    has_license: bool = False,
    has_date: bool = False,
    has_wikidata: bool = False,
) -> int:
    """
    Score metadata completeness (0-25).

    Higher score indicates more complete metadata, which suggests
    the uploader put effort into documenting the image.

    Args:
        has_description: Image has description text
        has_author: Image has author information
        has_license: Image has license information
        has_date: Image has capture date
        has_wikidata: Image has associated Wikidata entry

    Returns:
        Score from 0-25
    """
    score = 0
    if has_description:
        score += 8
    if has_author:
        score += 5
    if has_license:
        score += 4
    if has_date:
        score += 4
    if has_wikidata:
        score += 4
    return score


def score_technical_quality(
    width: Optional[int] = None,
    height: Optional[int] = None,
    mime_type: Optional[str] = None,
    file_size: Optional[int] = None,
) -> int:
    """
    Score technical image quality (0-30).

    Higher score indicates better technical quality. Penalties for small images
    and low file sizes. No score for file format (removed).

    Args:
        width: Image width in pixels
        height: Image height in pixels
        mime_type: MIME type (e.g., "image/jpeg") - NOT SCORED
        file_size: File size in bytes

    Returns:
        Score from 0-30
    """
    score = 0

    if width and height:
        is_portrait = height > width

        # Resolution score (0-20 points)
        # Orientation-aware thresholds (portrait: height≥1000px, landscape: width≥1333px)
        if is_portrait:
            # Portrait: height is more important
            if height >= 2250:  # >=5MP portrait
                score += 20
            elif height >= 1500:  # >=2.25MP portrait
                score += 15
            elif height >= 1000:  # >=1MP portrait
                score += 10
            elif height >= 720:  # HD minimum
                score += 5
            else:
                score -= 10  # Too small (<720px height)
        else:
            # Landscape: width is more important
            if width >= 2666:  # >=5MP landscape
                score += 20
            elif width >= 2000:  # >=2.5MP landscape
                score += 15
            elif width >= 1333:  # >=1MP landscape
                score += 10
            elif width >= 1280:  # HD minimum
                score += 5
            else:
                score -= 10  # Too small (<1280px width)

    # File size as quality indicator (0-10 points)
    if file_size:
        if file_size > 2_000_000:  # >2MB
            score += 10
        elif file_size > 1_000_000:  # >1MB
            score += 7
        elif file_size > 500_000:  # >500KB
            score += 5
        elif file_size < 100_000:  # <100KB - likely low quality
            score -= 5

    # No file format score (removed as requested)

    return max(score, 0)  # Minimum 0


def score_usage_signals(
    global_usage_count: int = 0,
    is_featured: bool = False,
    is_quality: bool = False,
) -> int:
    """
    Score usage and curation signals (0-15).

    Higher score indicates the image has been vetted by the community
    or is widely used, indicating quality and relevance.

    Args:
        global_usage_count: Number of Wikipedia articles using this image
        is_featured: Image has "Featured Picture" status
        is_quality: Image has "Quality Image" status

    Returns:
        Score from 0-15
    """
    score = 0

    # Global usage (capped at 10)
    score += min(global_usage_count * 2, 10)

    # Community awards
    if is_featured:
        score += 5  # Featured Picture - highest award
    if is_quality:
        score += 3  # Quality Image - reviewed but not featured

    return score


def calculate_age_penalty(days_old: Optional[int] = None) -> int:
    """
    Calculate age penalty score (-50 to +5).

    Older images receive penalties to ensure fresh content. Recent images
    (<=2 years) get a small bonus. Images with no date receive maximum penalty.

    Args:
        days_old: Age of image in days, or None if date is unknown

    Returns:
        Score from -50 to +5
    """
    # No date available - maximum penalty
    if days_old is None:
        return -50

    age_years = days_old / 365.25

    if age_years > 30:
        return -50  # Very old images (>30 years)
    elif age_years > 15:
        return -30  # Old images (>15 years)
    elif age_years > 2:
        # Linear penalty from -5 to -25 for 2-15 years
        ratio = (age_years - 2) / (15 - 2)  # 0 to 1
        return int(-5 + (ratio * -20))  # -5 to -25
    else:
        return 5  # Recent images (<=2 years): small bonus


def score_qid_match(has_qid: bool = False, matches_place_qid: bool = False) -> int:
    """
    Score QID (Wikidata entity) matching (0-15).

    Images linked to the same Wikidata entity as the GeoPlace get
    a significant score boost because they're verified to be related.

    Args:
        has_qid: Image has associated Wikidata QID
        matches_place_qid: Image's QID matches the GeoPlace's QID

    Returns:
        Score from 0-15
    """
    if matches_place_qid:
        return 15  # Perfect match - highly relevant
    elif has_qid:
        return 5  # Has QID but not matching
    else:
        return 0  # No QID


def score_distance_relevance(distance_m: float, search_radius_m: float) -> int:
    """
    Score distance relevance (0-20).

    Images closer to the query point or within the search radius get higher scores.
    This is particularly important for providers like Camptocamp where images are
    associated with waypoints that may not be the closest to the query point.

    Args:
        distance_m: Distance from query point in meters
        search_radius_m: Search radius in meters

    Returns:
        Score from 0-20
    """
    # Very close to query point (within 10m)
    if distance_m <= 10:
        return 20
    # Within search radius
    elif distance_m <= search_radius_m:
        # Linear interpolation: 20 -> 5 as distance increases
        ratio = distance_m / search_radius_m
        return int(20 - (ratio * 15))
    # Outside search radius but reasonable distance (up to 5x radius)
    elif distance_m <= search_radius_m * 5:
        # Heavy penalty for being outside search radius
        return max(0, 5 - int((distance_m - search_radius_m) / search_radius_m * 5))
    # Too far
    else:
        return 0
