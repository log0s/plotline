"""Structured logging configuration.

Configures structlog with JSON output in production and pretty console
output in development. Import configure_logging() in main.py, and
configure_script_logging() as the first statement of any script's main().
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import Settings, get_settings
from app.redact import redact_event_dict


def configure_logging(
    settings: Settings, *, renderer: structlog.types.Processor | None = None
) -> None:
    """Set up structlog + stdlib logging integration."""
    log_level = getattr(logging, settings.log_level, logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        # Carries extra={...} from stdlib logging calls into the event dict.
        # Without it, every `logger.info(msg, extra={"parcel_id": ...})` in the
        # codebase renders as the bare message.
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        # Render exc_info to text *before* scrubbing, so an httpx error whose
        # message embeds the request URL (and its key= / sig= parameters) is
        # scrubbed as a string rather than slipping past as an object.
        structlog.processors.format_exc_info,
        redact_event_dict,
    ]

    if renderer is None:
        if settings.app_env == "production":
            # JSON output for log aggregators
            renderer = structlog.processors.JSONRenderer()
        else:
            # Human-friendly console output for local dev
            renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Quiet noisy third-party loggers. httpx logs full request URLs at INFO,
    # which puts CENSUS_API_KEY (passed as a query param) in plaintext in the
    # log stream — our own service logs cover the same calls without it. The
    # redact_event_dict processor above is the backstop for the same shape
    # everywhere else (str(HTTPStatusError) carries the URL too).
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def configure_script_logging(settings: Settings | None = None) -> None:
    """Install a root handler for a script run from the command line.

    Scripts get none of the API's or the worker's bootstrap, so nothing
    installs a root handler: the root logger keeps its default WARNING
    level with no handler attached, and every INFO line the code a script
    calls emits is dropped before it is ever formatted. That is how the
    2026-08-25 completion sweep ran 112 admission waits and emitted none of
    them — the ``depth``/``cap`` fields on ``wait_for_admission_slot``'s
    line existed and reached nothing, so the scorecard's wait numbers had
    to be reconstructed from database timestamps
    (``docs/audits/2026-08-s2-year/LOGGING-FIX.md``).

    Console rendering regardless of ``app_env``: a script's stdout is an
    operator's terminal or a captured transcript, not a log aggregator, and
    a production script run would otherwise render JSON at a human.
    Colours only when that stdout is a terminal, so a redirected run does
    not fill a file with escape codes.
    """
    configure_logging(
        settings or get_settings(),
        renderer=structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
    )
