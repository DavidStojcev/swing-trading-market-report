"""Delivery package for email notifications and reports."""

from delivery.email_sender import (
    EmailServiceConfig,
    build_email_message,
    save_dry_run_email,
    send_email_report,
)

__all__ = [
    "EmailServiceConfig",
    "build_email_message",
    "send_email_report",
    "save_dry_run_email",
]
