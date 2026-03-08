from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from modeltrans.fields import TranslationField
from server.core.models import TimeStampedModel

from server.apps.categories.models import Category
from server.apps.organizations.models import Organization


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

    url = models.URLField(
        db_index=True,
        verbose_name=_("URL"),
        help_text=_(
            "The URL of the external link (translatable - defaults to first language)"
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

    def save(self, *args, skip_health_check=False, **kwargs):
        """
        Auto-generate identifier if not provided and run health check.

        Args:
            skip_health_check: If True, skip health check (useful for bulk imports)
        """
        if not self.identifier:
            self.identifier = self.generate_unique_identifier()

        # Auto-detect source organization from URL domain if not set
        if not self.source and self.url:
            self.source = self._auto_detect_source()

        # Auto-extract title from webpage if label is not provided
        if not self.label and self.url:
            self._auto_extract_title()

        # Run health check on save (unless skipped or no URL)
        if self.url and not skip_health_check:
            self.check_health()

        super().save(*args, **kwargs)

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
        from bs4 import BeautifulSoup

        try:
            # Fetch the webpage (stream to avoid loading full content)
            response = requests.get(
                url,
                timeout=10,
                stream=True,
                allow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; WodoreBot/1.0; +https://wodore.com)"
                },
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
            if og_title and og_title.get("content"):
                return og_title["content"].strip()

            # Try Twitter Card title
            twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
            if twitter_title and twitter_title.get("content"):
                return twitter_title["content"].strip()

            # Try regular HTML title
            title_tag = soup.find("title")
            if title_tag and title_tag.string:
                return title_tag.string.strip()

        except Exception:
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
        from urllib.parse import urlparse, unquote

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

    def check_health(self) -> dict:
        """
        Check the health of all translated URLs by making HEAD requests.

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
        import requests
        from django.utils import timezone

        # URLs to check (all available languages)
        urls_to_check = []
        for code in settings.LANGUAGE_CODES:
            url_attr = f"url_{code}"
            if hasattr(self, url_attr) and getattr(self, url_attr):
                urls_to_check.append((code, getattr(self, url_attr)))

        # If no language-specific URLs, check the default URL
        if not urls_to_check and self.url:
            urls_to_check.append(("default", self.url))

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
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; WodoreBot/1.0; +https://wodore.com)"
                    },
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
                errors.append(f"{lang}: {str(e)}")

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
    def generate_unique_identifier(cls, length: int = 6, max_attempts: int = 10) -> str:
        """
        Generate a unique short identifier.

        Args:
            length: Length of identifier (default 6)
            max_attempts: Maximum attempts to find unique identifier

        Returns:
            Unique identifier string

        Examples:
            "a3f9b2", "x7k2m9", "p4t8w1"
        """
        import secrets
        import string

        charset = string.ascii_lowercase + string.digits

        for attempt in range(max_attempts):
            identifier = "".join(secrets.choice(charset) for _ in range(length))

            if not cls._identifier_exists(identifier):
                return identifier

        # Fallback: try longer identifier
        return cls.generate_unique_identifier(length=length + 1)

    @classmethod
    def _identifier_exists(cls, identifier: str) -> bool:
        """Check if an identifier already exists in the database."""
        return cls.objects.filter(identifier=identifier).exists()

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
