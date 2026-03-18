# Logging
# https://docs.djangoproject.com/en/4.2/topics/logging/

# See also:
# 'Do not log' by Nikita Sobolev (@sobolevn)
# https://sobolevn.me/2020/03/do-not-log

import logging
import logging.config
import os
from typing import TYPE_CHECKING, Callable, final

import structlog


if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


class SlowQueryFilter(logging.Filter):
    """Filter DB logs to only include queries above a duration threshold."""

    def __init__(self, threshold_ms: int | None = None) -> None:
        super().__init__()
        self._threshold_ms = threshold_ms or int(
            os.getenv("SLOW_QUERY_THRESHOLD_MS", "200")
        )

    def filter(self, record: logging.LogRecord) -> bool:
        duration = getattr(record, "duration", None)
        if duration is None:
            return False
        return duration >= self._threshold_ms


def _get_log_level() -> str:
    """Get log level from environment variable."""
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if level_str not in valid_levels:
        level_str = "INFO"
    return level_str


def _is_debug() -> bool:
    """Check if we're in debug mode."""
    env = os.getenv("DJANGO_ENV", "development")
    return env == "development"


def _format_callsite(
    logger: logging.Logger, method_name: str, event_dict: dict
) -> dict:
    """Format logger name and lineno as '[logger:line]' for cleaner output."""
    logger_name = event_dict.pop("logger", None)
    lineno = event_dict.pop("lineno", None)

    # Remove module as we're using logger name instead
    event_dict.pop("module", None)

    if logger_name and lineno:
        # Store callsite info to be rendered at the end by custom renderer
        event_dict["_callsite"] = f"{logger_name}:{lineno}"

    return event_dict


class CustomConsoleRenderer(structlog.dev.ConsoleRenderer):
    """Custom console renderer that shows callsite at the end in brackets."""

    def __call__(self, logger, name, event_dict):
        """Render event with callsite at the end in dim blue."""
        # Extract callsite before rendering
        callsite = event_dict.pop("_callsite", None)

        # Render normally
        result = super().__call__(logger, name, event_dict)

        # Append callsite at the end if present, in dim blue color
        if callsite:
            # ANSI codes: \033[2m = dim, \033[34m = blue, \033[0m = reset
            dim_blue = "\033[2;34m"
            reset = "\033[0m"
            # ConsoleRenderer doesn't add newlines, so just append callsite
            result = result + f" {dim_blue}[{callsite}]{reset}"

        return result


class StructlogFormatter(logging.Formatter):
    """Custom formatter that processes Django logs through structlog."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = None
        self.processors = None

    def format(self, record):
        """Format a logging record using structlog."""
        # Build event dict from log record
        event_dict = {
            "event": record.getMessage(),
            "logger": record.name,
            "level": record.levelname.lower(),
        }

        # Add extra fields if present
        if hasattr(record, "status_code"):
            event_dict["status_code"] = record.status_code
        if hasattr(record, "request"):
            # Parse request info from message
            msg = record.getMessage()
            if '"' in msg:
                parts = msg.split('"')
                if len(parts) >= 2:
                    event_dict["request"] = parts[1]
                if len(parts) >= 3 and parts[2].strip():
                    status_parts = parts[2].strip().split()
                    if status_parts:
                        event_dict["status"] = status_parts[0]

        # Use the configured renderer if available
        if not self.renderer:
            # Get the configured renderer from structlog
            self.renderer = (
                structlog.get_config().get("processors", [])[-1]
                if structlog.is_configured()
                else None
            )

        # Format using structlog's processor
        try:
            if self.renderer and callable(self.renderer):
                result = self.renderer(None, record.levelname.lower(), event_dict)
                return result if isinstance(result, str) else str(result)
        except Exception:
            pass

        # Fallback to standard formatting
        return super().format(record)


def configure_structlog() -> None:
    """
    Configure structlog with Django integration.

    Uses colored console output in development, JSON in production.
    Automatically adds timestamp, log level, logger name, and callsite info.
    """
    is_debug = _is_debug()
    log_level = _get_log_level()

    # Development-only processors (callsite info)
    dev_processors = [
        # Short timestamp for development (HH:MM:SS)
        structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ),
    ]

    # Shared processors for all logs
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
    ]

    # Add development processors if in debug mode
    if is_debug:
        shared_processors.extend(dev_processors)
        # Format callsite as "logger:line" for cleaner output
        shared_processors.append(_format_callsite)
        # Create a separate chain for foreign (stdlib) loggers that includes callsite
        foreign_pre_chain = [
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            _format_callsite,
        ]
    else:
        # Production: add full callsite info for debugging
        shared_processors.append(
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.MODULE,
                ]
            )
        )
        # Add timestamp only in production (dev shows relative time)
        shared_processors.insert(0, structlog.processors.TimeStamper(fmt="iso"))
        # Use same chain for foreign loggers in production
        foreign_pre_chain = shared_processors

    # Choose renderer based on environment
    if is_debug:
        # Development: colored, readable console output
        # Shows: HH:MM:SS [level] message key=value... [module:line]
        renderer = CustomConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )
    else:
        # Production: JSON for Kubernetes/ELK
        renderer = structlog.processors.JSONRenderer()

    # Configure structlog to process standard logging
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.ExceptionPrettyPrinter(),
            # Bridge standard logging to structlog
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure Django's logging to use structlog formatter
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "slow_queries": {
                    "()": SlowQueryFilter,
                },
            },
            "formatters": {
                "structlog": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processor": renderer,
                    "foreign_pre_chain": foreign_pre_chain,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "structlog",
                },
            },
            "root": {
                "handlers": ["console"],
                "level": "WARNING",  # Only warnings and errors from third-party libs
            },
            "loggers": {
                "django": {
                    "handlers": ["console"],
                    "level": "INFO",
                    "propagate": False,
                },
                "django.db.backends": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "filters": ["slow_queries"],
                    "propagate": False,
                },
                "django.server": {
                    "handlers": [],  # Suppress Django dev server logs (they use custom formatter)
                    "level": "WARNING",
                    "propagate": False,
                },
                "django.request": {
                    "handlers": ["console"],
                    "level": "WARNING",  # Show warnings and errors (including 404s if configured)
                    "propagate": False,
                },
                "security": {
                    "handlers": ["console"],
                    "level": "ERROR",
                    "propagate": False,
                },
                # Suppress verbose HTTP library logs
                "httpx": {
                    "level": "WARNING",
                    "propagate": False,
                },
                "httpcore": {
                    "level": "WARNING",
                    "propagate": False,
                },
                "urllib3": {
                    "level": "WARNING",
                    "propagate": False,
                },
                # Your app logs - add all server.apps.* loggers here
                "server": {
                    "handlers": ["console"],
                    "level": log_level,
                    "propagate": False,
                },
            },
        }
    )


# Configure structlog on module import (only once)
if not structlog.is_configured():
    configure_structlog()


@final
class LoggingContextVarsMiddleware:
    """Used to reset ContextVars in structlog on each request."""

    def __init__(
        self,
        get_response: "Callable[[HttpRequest], HttpResponse]",
    ) -> None:
        """Django's API-compatible constructor."""
        self.get_response = get_response

    def __call__(self, request: "HttpRequest") -> "HttpResponse":
        """
        Handle requests.

        Add your logging metadata here.
        Example: https://github.com/jrobichaud/django-structlog
        """
        response = self.get_response(request)
        structlog.contextvars.clear_contextvars()
        return response
