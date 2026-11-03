"""Email delivery service supporting SMTP TLS, inline CID charts, and .eml dry-run export."""

from dataclasses import dataclass, field
from email import encoders
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
from pathlib import Path
import re
import smtplib
from typing import Any, Dict, List, Optional, Tuple

from data.calendar import PeriodInfo
from render.charts import GeneratedChart
from scoring.engine import Scorecard

logger = logging.getLogger(__name__)


@dataclass
class EmailServiceConfig:
    """SMTP configuration resolved from environment variables or settings."""
    enabled: bool = False
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    email_from: str = field(default_factory=lambda: os.getenv("EMAIL_FROM", ""))
    email_to: List[str] = field(default_factory=lambda: [e.strip() for e in os.getenv("EMAIL_TO", "").split(",") if e.strip()])
    require_tls: bool = True

    @property
    def is_configured(self) -> bool:
        """Check if all required SMTP connection credentials exist."""
        return bool(self.smtp_host and self.email_from and self.email_to)


def build_email_message(
    period: PeriodInfo,
    scorecard: Optional[Scorecard],
    html_content: str,
    md_content: str,
    charts: Dict[str, GeneratedChart],
    html_attachment_path: Optional[Path] = None,
    sender: Optional[str] = None,
    recipients: Optional[List[str]] = None,
) -> MIMEMultipart:
    """Build compliant RFC 2822 multipart email with plain-text fallback, inline CID charts, and attachment."""
    verdict_str = scorecard.verdict if scorecard else "Neutral"
    subject = f"[{period.report_type.capitalize()}] Market Report - {period.session_date} - {verdict_str}"

    from_addr = sender or os.getenv("EMAIL_FROM", "reports@marketreport.local")
    to_addrs = recipients or [e.strip() for e in os.getenv("EMAIL_TO", "user@example.com").split(",") if e.strip()]

    # Root: multipart/mixed (body + attached files)
    msg_root = MIMEMultipart("mixed")
    msg_root["Subject"] = subject
    msg_root["From"] = from_addr
    msg_root["To"] = ", ".join(to_addrs)
    msg_root["X-Report-Type"] = period.report_type
    msg_root["X-Session-Date"] = period.session_date

    # Container for body: multipart/alternative (plain-text or rich HTML)
    msg_alternative = MIMEMultipart("alternative")

    # 1. Plain-text fallback
    plain_text_summary = [
        f"{period.report_type.upper()} US MARKET REPORT",
        f"As of: {period.session_date} (Evaluation Window: {period.current_start} to {period.current_end})",
        f"Verdict: {verdict_str.upper()} (Trend Score: {scorecard.normalized_score:+.2f} if scorecard else 0.00)",
        "=" * 60,
        "",
        "KEY DRIVERS:",
    ]
    if scorecard:
        for r in scorecard.summary_reasons:
            plain_text_summary.append(f" - {r}")
        plain_text_summary.append("")
        plain_text_summary.append("TOP BULLISH FACTORS:")
        for bf in scorecard.top_bullish_factors:
            plain_text_summary.append(f" + {bf}")
        plain_text_summary.append("")
        plain_text_summary.append("TOP BEARISH FACTORS:")
        for br in scorecard.top_bearish_factors:
            plain_text_summary.append(f" - {br}")

    plain_text_summary.append("")
    plain_text_summary.append("Please view the attached HTML file or enable rich HTML display to review full charts and technical tables.")
    plain_text_summary.append("For informational purposes only. Not financial advice.")

    msg_alternative.attach(MIMEText("\n".join(plain_text_summary), "plain", "utf-8"))

    # 2. Rich HTML with inline CID images (multipart/related)
    msg_related = MIMEMultipart("related")

    # Replace chart base64 data URIs with CID references for email client compatibility
    email_html = html_content
    cid_images: List[Tuple[str, bytes]] = []

    for key, chart in charts.items():
        if chart.is_available and chart.base64_data:
            cid = f"chart_{key}"
            # Replace data URI or image src with cid:
            pattern = re.compile(rf'src=["\']data:image/png;base64,{re.escape(chart.base64_data)}["\']')
            email_html = pattern.sub(f'src="cid:{cid}"', email_html)

            # Also replace any relative file paths with cid
            if chart.file_path:
                fname = Path(chart.file_path).name
                email_html = email_html.replace(f'src="{fname}"', f'src="cid:{cid}"')
                email_html = email_html.replace(f'src="charts/{fname}"', f'src="cid:{cid}"')

            # Decode bytes for MIME attachment
            import base64
            img_bytes = base64.b64decode(chart.base64_data)
            cid_images.append((cid, img_bytes))

    msg_related.attach(MIMEText(email_html, "html", "utf-8"))

    # Attach inline CID images
    for cid, img_bytes in cid_images:
        img_part = MIMEImage(img_bytes, "png")
        img_part.add_header("Content-ID", f"<{cid}>")
        img_part.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        msg_related.attach(img_part)

    msg_alternative.attach(msg_related)
    msg_root.attach(msg_alternative)

    # 3. Attach full standalone HTML report as file
    if html_attachment_path and html_attachment_path.exists():
        try:
            with open(html_attachment_path, "rb") as f:
                attachment_bytes = f.read()
            att_part = MIMEBase("application", "octet-stream")
            att_part.set_payload(attachment_bytes)
            encoders.encode_base64(att_part)
            att_name = f"{period.report_type}_{period.session_date}_report.html"
            att_part.add_header("Content-Disposition", f"attachment; filename={att_name}")
            msg_root.attach(att_part)
        except Exception as e:
            logger.warning("Failed to attach HTML report file to email: %s", e)

    return msg_root


def send_email_report(
    msg: MIMEMultipart,
    config: EmailServiceConfig,
) -> Tuple[bool, str]:
    """Deliver report email via SMTP with TLS."""
    if not config.is_configured:
        err = "SMTP is not configured (missing SMTP_HOST, EMAIL_FROM, or EMAIL_TO)."
        logger.warning(err)
        return False, err

    try:
        logger.info("Connecting to SMTP server: %s:%d (TLS=%s)", config.smtp_host, config.smtp_port, config.require_tls)
        server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30)
        server.ehlo()

        if config.require_tls:
            server.starttls()
            server.ehlo()

        if config.smtp_user and config.smtp_password:
            server.login(config.smtp_user, config.smtp_password)

        recipients = [r.strip() for r in msg["To"].split(",") if r.strip()]
        server.send_message(msg, from_addr=config.email_from, to_addrs=recipients)
        server.quit()

        success_msg = f"Email successfully dispatched to {len(recipients)} recipient(s): {', '.join(recipients)}"
        logger.info(success_msg)
        return True, success_msg
    except Exception as e:
        err_msg = f"Failed to send email via SMTP: {e}"
        logger.error(err_msg)
        return False, err_msg


def save_dry_run_email(
    msg: MIMEMultipart,
    output_path: Path,
) -> Path:
    """Save complete MIME email to an .eml file on disk for inspection and testing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(msg.as_bytes())
    logger.info("Saved dry-run email artifact to: %s", output_path)
    return output_path
