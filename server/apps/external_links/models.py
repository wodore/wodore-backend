from __future__ import annotations

from typing import Any, override

from modeltrans.fields import TranslationField

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils.translation import gettext_lazy as _

from server.apps.categories.models import Category
from server.apps.organizations.models import Organization
from server.core.models import TimeStampedModel

from .uri import is_web_url, scheme_of, validate_url_for_scheme


class ReviewStatus(models.TextChoices):
    """Review status for external links."""

    NEW = "new", _("New")
    REVIEW = "review", _("Review")
    WORK = "work", _("Work")
    DONE = "done", _("Done")


class ExternalLink(TimeStampedModel):
    """
    External links with full i18n, review workflow, and monitoring.

    Can be associated with GeoPlaces, Huts, and other models through
    appropriate through-models.
    """

    # Core fields
    identifier = models.CharField(
        max_length=10,
        unique=True,
        db_index=True,
        verbose_name=_("Identifier"),
        help_text=_("Short unique identifier (6 characters)"),
    )

    url = models.CharField(
        max_length=200,
        db_index=True,
        validators=[validate_url_for_scheme],
        verbose_name=_("URL"),
        help_text=_(
            "The URL of the external link (translatable - defaults to first "
            "language). Any scheme its URI kind accepts: http(s), tel:, mailto:"
        ),
    )

    source = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_links",
        verbose_name=_("Source"),
        help_text=_("Organization that provided this link (optional)"),
    )

    # Categorization
    link_type = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="external_links",
        verbose_name=_("Link Type"),
        help_text=_("Type of link (e.g., social, website, api, document)"),
    )

    # Typed URIs (external-link-uris): the transport kind — a second,
    # independent dimension next to the loose link_type purposes.
    uri_kind = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        null=False,  # introduced nullable, backfilled, then NOT NULL (0010)
        blank=True,  # forms may leave it empty — save() derives from the URL
        db_index=True,
        related_name="+",
        limit_choices_to={"parent__slug": "uri"},
        verbose_name=_("URI Kind"),
        help_text=_(
            "Transport kind of the URL (uri.phone / uri.email / uri.website); "
            "derived from the URL's scheme on save"
        ),
    )

    # Translatable content
    i18n = TranslationField(fields=("label", "description", "url"))

    label = models.CharField(
        max_length=200,
        verbose_name=_("Label"),
        help_text=_("Short label for the link (translatable)"),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Detailed description of the link (translatable)"),
    )

    # Review workflow
    review_status = models.CharField(
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.DONE,
        db_index=True,
        verbose_name=_("Review Status"),
        help_text=_("Editorial state - links shown only when 'done'"),
    )

    review_comment = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Review Comment"),
        help_text=_("Internal reviewer note"),
    )

    # Link health
    last_checked = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Checked"),
        help_text=_("When this link was last checked for accessibility"),
    )

    response_code = models.SmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Response Code"),
        help_text=_("Last HTTP response code (e.g., 200, 404)"),
    )

    failure_count = models.SmallIntegerField(
        default=0,
        verbose_name=_("Failure Count"),
        help_text=_("Number of consecutive check failures"),
    )

    # Template support
    is_template = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Is Template"),
        help_text=_(
            "Auto-detected: True if URL contains placeholders like {osm_type} or {osm_id}"
        ),
    )

    template_vars = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Template Variables"),
        help_text=_(
            "Available template variables and their example values for health check. "
            "Example: {'osm_type': 'node', 'osm_id': '123456', 'source_id': 'node/123456'}"
        ),
    )

    run_health_check = models.BooleanField(
        default=True,
        verbose_name=_("Run Health Check"),
        help_text=_(
            "Whether to run health checks on this link. "
            "Disable for templates without example values."
        ),
    )

    # Metadata
    is_public = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Public"),
        help_text=_("Show this link to public users"),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Active"),
        help_text=_("Whether this link is active (soft delete)"),
    )

    class Meta:
        verbose_name = _("External Link")
        verbose_name_plural = _("External Links")
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["url"]),
            models.Index(fields=["is_active", "is_public"]),
            models.Index(fields=["review_status"]),
            models.Index(fields=["last_checked"]),
            models.Index(fields=["link_type"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_review_status_valid",
                condition=models.Q(review_status__in=["new", "review", "work", "done"]),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_response_code_valid",
                condition=models.Q(response_code__isnull=True)
                | models.Q(response_code__gte=100) & models.Q(response_code__lte=599),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_failure_count_positive",
                condition=models.Q(failure_count__gte=0),
            ),
        ]

    @override
    def save(
        self,
        *args: Any,
        skip_health_check: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Auto-generate identifier if not provided and run health check.

        A unique collision on the freshly minted identifier retries
        with a re-mint inside a savepoint (the constraint is the
        authority — the old probe-based generation was TOCTOU-racy).

        Args:
            skip_health_check: If True, skip health check (useful for bulk imports)
        """
        minted_identifier = not self.identifier
        if minted_identifier:
            self.identifier = self.generate_unique_identifier()

        # Typed URIs (external-link-uris): the kind follows the URL —
        # one derivation step covers admin forms, imports and API
        # writes alike (no endpoint or signal).
        self._derive_uri_kind()

        # Auto-detect template from URL pattern
        if self.url and "{" in self.url and "}" in self.url:
            self.is_template = True
        else:
            self.is_template = False

        # Auto-detect source organization from URL domain if not set
        # (web-only behaviour — tel:/mailto: URLs never hit the network)
        if (
            not self.source
            and self.url
            and not self.is_template
            and is_web_url(self.url)
        ):
            self.source = self._auto_detect_source()

        # Auto-extract title from webpage if label is not provided
        # (web-only behaviour)
        if (
            not self.label
            and self.url
            and not self.is_template
            and is_web_url(self.url)
        ):
            self._auto_extract_title()

        # Only run health check if enabled and either:
        # - Not a template, OR
        # - Is a template with example values
        should_check = (
            self.run_health_check
            and self.url
            and is_web_url(self.url)
            and not skip_health_check
            and (not self.is_template or self.template_vars)
        )

        if should_check:
            self.check_health()

        for attempt in range(3):
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError:
                if not minted_identifier or attempt == 2:
                    raise
                self.identifier = self.generate_unique_identifier()

    def _uri_kind_schemes(self) -> set[str]:
        """Schemes the current ``uri_kind`` accepts (empty set if unset)."""
        if self.uri_kind_id is None:
            return set()
        extra = getattr(self.uri_kind, "extra", None) or {}
        return {str(s).lower() for s in extra.get("schemes", [])}

    @classmethod
    def derive_uri_kind_for_url(cls, url: str) -> Category | None:
        """Vocabulary kind whose accepted schemes contain the URL's scheme."""
        scheme = scheme_of(url)
        if scheme is None:
            return None
        return Category.objects.filter(
            parent__slug="uri",
            is_active=True,
            extra__schemes__contains=scheme,
        ).first()

    def _derive_uri_kind(self) -> None:
        """Make the URI kind follow the URL (external-link-uris).

        Re-derives whenever the URL's scheme falls outside the current
        kind's accepted schemes (enter or change); a manual override
        within the kind's schemes is honored; an unknown scheme is
        rejected. ``save()`` calls this — the derivation is the reason
        kindless saves cannot happen once the column is NOT NULL.
        """
        if not self.url:
            return
        scheme = scheme_of(self.url)
        if scheme is None:
            msg = f"'{self.url}' has no URL scheme."
            raise ValidationError({"url": msg})
        if scheme in self._uri_kind_schemes():
            return  # entered/overridden within the kind's schemes
        derived = self.derive_uri_kind_for_url(self.url)
        if derived is None:
            msg = (
                f"URL scheme '{scheme}:' matches no URI kind "
                "(vocabulary: uri.phone/uri.email/uri.website)."
            )
            raise ValidationError({"url": msg})
        self.uri_kind = derived

    @override
    def clean(self) -> None:
        """Scheme↔kind consistency + URI well-formedness (external-link-uris).

        ``save()`` skips ``clean()`` — the save-path derivation is the
        primary guard; this mirrors it for form validation.
        """
        super().clean()
        kind = self.uri_kind
        if kind is not None:
            parent_slug = (
                Category.objects.filter(pk=kind.parent_id)
                .values_list("slug", flat=True)
                .first()
            )
            if parent_slug != "uri":
                msg = "URI kind must be a category under the 'uri' parent."
                raise ValidationError({"uri_kind": msg})
        self._validate_urls_against_kind()

    def _validate_urls_against_kind(self) -> None:
        """Validate every populated URL variant (default + languages)."""
        accepted = self._uri_kind_schemes()
        variants: list[str] = [self.url] if self.url else []
        for code in settings.LANGUAGE_CODES:
            value = getattr(self, f"url_{code}", None)
            if value:
                variants.append(value)
        for value in variants:
            validate_url_for_scheme(value)
            scheme = scheme_of(value)
            if accepted and scheme not in accepted:
                msg = (
                    f"URL scheme '{scheme}:' is not accepted by URI kind "
                    f"'{self.uri_kind}'."
                )
                raise ValidationError({"url": msg})

    def _auto_extract_title(self) -> None:
        """
        Auto-extract title from webpage for all language URLs.

        Tries to extract titles from:
        1. Open Graph meta tag (og:title)
        2. Twitter Card meta tag (twitter:title)
        3. HTML <title> tag
        4. Falls back to generating a label from the URL

        Sets the label for each language-specific URL.
        """

        # Get all language-specific URLs
        urls_to_fetch = []

        for code in settings.LANGUAGE_CODES:
            url_attr = f"url_{code}"
            label_attr = f"label_{code}"

            # Check if this language has a URL and no label
            if hasattr(self, url_attr) and getattr(self, url_attr):
                if not hasattr(self, label_attr) or not getattr(self, label_attr):
                    urls_to_fetch.append((code, getattr(self, url_attr)))

        # If no language-specific URLs, check default
        if not urls_to_fetch and self.url and not self.label:
            urls_to_fetch.append(("default", self.url))

        # Extract titles for each URL
        for lang, url in urls_to_fetch:
            title = self._extract_title_from_url(url)

            # Set the title for this language
            if lang == "default":
                self.label = title
            else:
                setattr(self, f"label_{lang}", title)

    def _extract_title_from_url(self, url: str) -> str:
        """
        Extract title from a single URL.

        Args:
            url: The URL to fetch and extract title from

        Returns:
            Extracted title or generated label from URL
        """
        import requests
        from bs4 import BeautifulSoup, Tag

        try:
            # Fetch the webpage (stream to avoid loading full content)
            response = requests.get(
                url,
                timeout=10,
                stream=True,
                allow_redirects=True,
                headers={"User-Agent": settings.BOT_AGENT},
            )
            response.raise_for_status()

            # Read only first 50KB (enough for <head> section)
            content = b""
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                if len(content) >= 50000:  # 50KB should be enough for head section
                    break

            response.close()

            # Parse HTML
            soup = BeautifulSoup(content, "html.parser")

            # Try Open Graph title
            og_title = soup.find("meta", property="og:title")
            if isinstance(og_title, Tag) and og_title.get("content"):
                return str(og_title["content"]).strip()

            # Try Twitter Card title
            twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
            if isinstance(twitter_title, Tag) and twitter_title.get("content"):
                return str(twitter_title["content"]).strip()

            # Try regular HTML title
            title_tag = soup.find("title")
            if isinstance(title_tag, Tag) and title_tag.string:
                return title_tag.string.strip()

        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # If fetching fails, fall through to URL-based label
            pass

        # Fallback: Generate label from URL
        return self._generate_label_from_url(url)

    def _generate_label_from_url(self, url: str) -> str:
        """
        Generate a readable label from URL.

        Extracts the last path segment or domain name and makes it readable.

        Examples:
            https://example.com/my-page → "My Page"
            https://example.com/about-us/ → "About Us"
            https://example.com → "Example"

        Args:
            url: The URL to generate label from

        Returns:
            Human-readable label
        """
        from urllib.parse import unquote, urlparse

        parsed = urlparse(url)

        # Try to get last path segment
        path = parsed.path.rstrip("/")
        if path:
            # Get last segment
            segments = path.split("/")
            last_segment = segments[-1]

            # Decode URL encoding
            last_segment = unquote(last_segment)

            # Remove common file extensions
            last_segment = last_segment.split(".")[0]

            # Replace common separators with spaces
            last_segment = last_segment.replace("-", " ").replace("_", " ")

            # Capitalize words
            label = " ".join(word.capitalize() for word in last_segment.split())

            if label:
                return label

        # Fallback to domain name
        domain = parsed.netloc

        # Remove www. and TLD
        domain = domain.replace("www.", "")
        domain_parts = domain.split(".")
        if len(domain_parts) > 1:
            domain = domain_parts[0]

        return domain.capitalize()

    def _auto_detect_source(self) -> Organization | None:
        """
        Auto-detect source organization by matching URL domain.

        Matches the link's domain against organization URLs.
        Handles www variants (e.g., www.sac-cas.ch and sac-cas.ch).

        Returns:
            Matching Organization or None if no match found
        """
        from urllib.parse import urlparse

        if not self.url:
            return None

        # Extract domain from link URL
        parsed = urlparse(self.url)
        link_domain = parsed.netloc.lower()

        if not link_domain:
            return None

        # Generate domain variants (with and without www)
        domains_to_check = [link_domain]

        if link_domain.startswith("www."):
            # If link has www, also check without www
            domains_to_check.append(link_domain[4:])
        else:
            # If link has no www, also check with www
            domains_to_check.append(f"www.{link_domain}")

        # Check all organizations for matching domains
        organizations = Organization.objects.filter(is_active=True)

        for org in organizations:
            if not org.url:
                continue

            # Extract domain from organization URL
            org_parsed = urlparse(org.url)
            org_domain = org_parsed.netloc.lower()

            # Check if any domain variant matches
            if org_domain in domains_to_check:
                return org

        return None

    def check_health(self) -> dict[str, Any]:
        """
        Check the health of all translated URLs by making HEAD requests.

        For template URLs, substitutes template_vars before checking.

        Updates the following fields:
        - last_checked: Current timestamp
        - response_code: Best HTTP status code across all languages
        - failure_count: Increments on failure, resets on success

        Handles review workflow:
        - On failure: Sets review_status to "review" and adds comment
        - On recovery: Resets to "done" if it was a health check failure

        Returns:
            Dictionary with health check results for all languages
        """
        # Non-web kinds (tel:, mailto:) are exempt by policy — never
        # network-check them (external-link-uris; defensive: the
        # selector and save() gate already skip them).
        if not is_web_url(self.url):
            return {
                "success": True,
                "skipped": True,
                "error": "Non-web URI kind - health check skipped",
            }

        import requests

        from django.utils import timezone

        # Check if template without example values
        if self.is_template and not self.template_vars:
            return {
                "success": False,
                "error": "Template link without example values - health check skipped",
            }

        # URLs to check (all available languages)
        urls_to_check = []
        for code in settings.LANGUAGE_CODES:
            url_attr = f"url_{code}"
            if hasattr(self, url_attr) and getattr(self, url_attr):
                url = getattr(self, url_attr)
                # Substitute template variables if needed
                if self.is_template and self.template_vars:
                    try:
                        url = url.format(**self.template_vars)
                    except KeyError as e:
                        return {
                            "success": False,
                            "error": f"Missing template variable: {e}",
                        }
                urls_to_check.append((code, url))

        # If no language-specific URLs, check the default URL
        if not urls_to_check and self.url:
            url = self.url
            # Substitute template variables if needed
            if self.is_template and self.template_vars:
                try:
                    url = url.format(**self.template_vars)
                except KeyError as e:
                    return {
                        "success": False,
                        "error": f"Missing template variable: {e}",
                    }
            urls_to_check.append(("default", url))

        if not urls_to_check:
            return {"success": False, "error": "No URLs to check"}

        # Check each language
        results = {}
        best_status_code = None
        any_success = False
        any_failure = False
        errors = []

        for lang, url in urls_to_check:
            try:
                import time

                start_time = time.time()

                response = requests.head(
                    url,
                    timeout=20,
                    allow_redirects=True,
                    headers={"User-Agent": settings.BOT_AGENT},
                )

                response_time_ms = int((time.time() - start_time) * 1000)

                results[lang] = {
                    "success": True,
                    "status_code": response.status_code,
                    "url": url,
                    "response_time_ms": response_time_ms,
                }

                # Track best status code
                if 200 <= int(response.status_code) < 300:
                    # Only 2xx codes are successful
                    results[lang]["success"] = True
                    any_success = True
                    if (
                        best_status_code is None
                        or response.status_code < best_status_code
                    ):
                        best_status_code = response.status_code
                else:
                    # Everything else (3xx, 4xx, 5xx) are failures
                    results[lang]["success"] = False
                    any_failure = True
                    if (
                        best_status_code is None
                        or response.status_code < best_status_code
                    ):
                        best_status_code = response.status_code

            except requests.RequestException as e:
                results[lang] = {
                    "success": False,
                    "error": str(e),
                    "url": url,
                }
                any_failure = True
                errors.append(f"{lang}: {e!s}")

        # Update health fields
        self.last_checked = timezone.now()
        self.response_code = best_status_code

        # Handle review state based on health
        health_check_failure_marker = "[HEALTH CHECK FAILURE]"

        if any_failure:
            # At least one language failed - mark as needs review
            self.failure_count = (self.failure_count or 0) + 1

            # Set review status to "review" if it was "done" and hasn't been manually reviewed
            if self.review_status in ReviewStatus.DONE:
                # Build detailed results string for all languages
                results_summary = []
                for lang, result in results.items():
                    if result.get("success"):
                        results_summary.append(
                            f"  {lang}: PASS [{result['status_code']}] | {result['response_time_ms']}ms | {result['url']}"
                        )
                    elif result.get("error"):
                        results_summary.append(
                            f"  {lang}: FAIL [{result.get('error', 'Unknown error')}] | - | {result['url']}"
                        )
                    else:
                        results_summary.append(
                            f"  {lang}: FAIL [{result['status_code']}] | {result['response_time_ms']}ms | {result['url']}"
                        )

                self.review_status = ReviewStatus.REVIEW
                self.review_comment = (
                    f"{health_check_failure_marker} "
                    f"Health check failed on {timezone.now().strftime('%Y-%m-%d %H:%M')}.\n"
                    f"Results:\n" + "\n".join(results_summary)
                )

        elif any_success:
            # At least one language succeeded
            self.failure_count = 0

            # Reset to "done" if it was a health check failure
            if (
                self.review_status == ReviewStatus.REVIEW
                and self.review_comment
                and health_check_failure_marker in self.review_comment
            ):
                self.review_status = ReviewStatus.DONE
                self.review_comment = ""

        return {
            "success": any_success,
            "any_failure": any_failure,
            "results": results,
            "best_status_code": best_status_code,
            "failure_count": self.failure_count,
        }

    @classmethod
    def generate_unique_identifier(cls, length: int = 6) -> str:
        """
        Mint a random short identifier (``[a-z0-9]``, cryptographic
        source) — a pure function with no database access.

        Uniqueness is enforced by ``save()``, which retries on the
        unique constraint inside a savepoint (the former probe loop
        here was TOCTOU-racy and cost one query per attempt).

        Examples:
            "a3f9b2", "x7k2m9", "p4t8w1"
        """
        import secrets
        import string

        charset = string.ascii_lowercase + string.digits
        return "".join(secrets.choice(charset) for _ in range(length))

    def render_url(self, lang: str | None = None, **kwargs: str) -> str:
        """
        Render template URL with provided variables.

        Args:
            lang: Language code (e.g., 'de', 'en', 'fr', 'it'). If None, uses current language.
            **kwargs: Template variables (e.g., osm_type="node", osm_id="123456")

        Returns:
            Rendered URL for the specified language

        Raises:
            ValueError: If missing template variable

        Examples:
            link.render_url(osm_type="node", osm_id="123456")
            # Returns: "https://mapcomplete.org/transit.html#node/123456"

            link.render_url(lang="de", source_id="node/123456")
            # Returns German URL with substituted variables
        """
        from django.utils import translation

        # Determine language
        if lang is None:
            lang = translation.get_language()

        # Get URL for the specified language
        url_attr = f"url_{lang}"
        if hasattr(self, url_attr) and getattr(self, url_attr):
            url = getattr(self, url_attr)
        else:
            # Fallback to default URL
            url = self.url

        if not self.is_template:
            return url

        try:
            return url.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Missing template variable: {e}")

    def __str__(self) -> str:
        """Return a concise string representation with truncated URL."""
        max_url_length = 50
        url = self.url_i18n

        if len(url) > max_url_length:
            url = url[:max_url_length] + "..."

        return f"{self.label_i18n} ({url})"

    @property
    def label_i18n(self) -> str:
        """Get the translated label."""
        return getattr(self, "label_de", self.label)

    @property
    def url_i18n(self) -> str:
        """Get the translated URL (falls back to default language)."""
        return getattr(self, "url_de", self.url)

    @property
    def description_i18n(self) -> str:
        """Get the translated description."""
        return getattr(self, "description_de", self.description)
