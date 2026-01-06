"""
Custom email backend for staging environment that rewrites recipient emails.

This backend wraps the standard SMTP backend and rewrites all recipient emails
(to, cc, bcc) to a controlled domain, except for whitelisted addresses.

Example:
    user@example.com -> info+staging_user_AT_example_DOT_com@wodore.com
"""

from typing import List

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.core.mail.message import EmailMessage


class StagingEmailBackend(SMTPBackend):
    """
    Email backend that rewrites recipient emails for staging environment.

    Rewrites all recipient emails to a controlled domain while preserving
    the original email in the address for debugging purposes.

    Configuration (in settings):
        STAGING_EMAIL_REWRITE_ENABLED: bool - Enable/disable rewriting (default: True)
        STAGING_EMAIL_REWRITE_TO: str - Base email to rewrite to (defaults to first DJANGO_ADMIN_EMAILS)
        STAGING_EMAIL_WHITELIST: list - Additional emails to whitelist (optional)

    Automatically whitelists:
        - SERVER_EMAIL
        - DEFAULT_FROM_EMAIL
        - All emails in DJANGO_ADMIN_EMAILS
        - All emails from @wodore.com domain
    """

    def send_messages(self, email_messages: List[EmailMessage]) -> int:
        """
        Send messages after rewriting recipient addresses.

        Args:
            email_messages: List of EmailMessage objects to send

        Returns:
            Number of messages sent successfully
        """
        if not getattr(settings, "STAGING_EMAIL_REWRITE_ENABLED", True):
            return super().send_messages(email_messages)

        # Rewrite recipients in all messages
        for message in email_messages:
            message.to = [self._rewrite_email(email) for email in message.to]
            message.cc = [self._rewrite_email(email) for email in message.cc]
            message.bcc = [self._rewrite_email(email) for email in message.bcc]

            # Add original recipients to subject for debugging
            original_to = getattr(message, "_original_to", None)
            if original_to and original_to != message.to:
                message.subject = (
                    f"[Staging: {', '.join(original_to)}] {message.subject}"
                )

        return super().send_messages(email_messages)

    def _rewrite_email(self, email: str) -> str:
        """
        Rewrite an email address if it's not whitelisted.

        Args:
            email: Email address to potentially rewrite

        Returns:
            Original email if whitelisted, otherwise rewritten email
        """
        email = email.strip()

        if self._is_whitelisted(email):
            return email

        return self._transform_email(email)

    def _is_whitelisted(self, email: str) -> bool:
        """
        Check if an email should be whitelisted (not rewritten).

        Args:
            email: Email address to check

        Returns:
            True if email should not be rewritten
        """
        email_lower = email.lower()

        # Whitelist wodore.com domain
        if "@wodore.com" in email_lower:
            return True

        # Whitelist settings-defined emails
        whitelist = set()

        # Add SERVER_EMAIL
        if hasattr(settings, "SERVER_EMAIL") and settings.SERVER_EMAIL:
            whitelist.add(settings.SERVER_EMAIL.lower())

        # Add DEFAULT_FROM_EMAIL
        if hasattr(settings, "DEFAULT_FROM_EMAIL") and settings.DEFAULT_FROM_EMAIL:
            whitelist.add(settings.DEFAULT_FROM_EMAIL.lower())

        # Add DJANGO_ADMIN_EMAILS (list of [name, email] pairs)
        if hasattr(settings, "DJANGO_ADMIN_EMAILS"):
            for admin_entry in settings.DJANGO_ADMIN_EMAILS:
                if isinstance(admin_entry, list) and len(admin_entry) >= 2:
                    # Second element is the email
                    whitelist.add(admin_entry[1].lower())
                elif isinstance(admin_entry, str):
                    whitelist.add(admin_entry.lower())

        # Add custom whitelist
        if hasattr(settings, "STAGING_EMAIL_WHITELIST"):
            custom_whitelist = settings.STAGING_EMAIL_WHITELIST
            if isinstance(custom_whitelist, (list, tuple)):
                whitelist.update(email.lower() for email in custom_whitelist)

        return email_lower in whitelist

    def _transform_email(self, email: str) -> str:
        """
        Transform an email address to the staging format.

        Example:
            john.doe@gmail.com -> info+staging_johnDOTdoe_AT_gmail_DOT_com@wodore.com

        Args:
            email: Original email address

        Returns:
            Transformed email address
        """
        # Get default email from settings (priority order):
        # 1. STAGING_EMAIL_REWRITE_TO (if explicitly set)
        # 2. First email in DJANGO_ADMIN_EMAILS (format: [[name, email], ...])
        # 3. Fallback to None (will raise error)

        default_email = None

        # Try to get from DJANGO_ADMIN_EMAILS
        try:
            admin_emails = getattr(settings, "DJANGO_ADMIN_EMAILS", [])
            if admin_emails and len(admin_emails) > 0:
                first_admin = admin_emails[0]
                if isinstance(first_admin, list) and len(first_admin) >= 2:
                    # Format is [[name, email], ...] - take the email part (index 1)
                    default_email = first_admin[1]
                elif isinstance(first_admin, str):
                    # Fallback if it's just a string
                    default_email = first_admin
        except (IndexError, TypeError, AttributeError):
            pass

        rewrite_to = getattr(settings, "STAGING_EMAIL_REWRITE_TO", None)
        if rewrite_to is None:
            rewrite_to = default_email

        if rewrite_to is None:
            raise ValueError(
                "STAGING_EMAIL_REWRITE_TO or DJANGO_ADMIN_EMAILS must be set"
            )

        # Parse the base email (e.g., 'info@wodore.com' -> 'info', 'wodore.com')
        if "@" in rewrite_to:
            base_local, base_domain = rewrite_to.rsplit("@", 1)
        else:
            raise ValueError(
                "Wrong e-mail format for staging email address ({})".format(rewrite_to)
            )

        # Transform original email: replace special characters
        transformed = email.replace("@", "_AT_")
        transformed = transformed.replace(".", "_DOT_")
        transformed = transformed.replace("+", "_PLUS_")

        # Build new email with + addressing
        new_email = f"{base_local}+staging_{transformed}@{base_domain}"

        return new_email
