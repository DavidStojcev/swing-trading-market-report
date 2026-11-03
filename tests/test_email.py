"""Unit tests for Stage 4 email builder, MIME structure, dry-run export, and failure handling."""

import email
from pathlib import Path
import pytest

from data.calendar import PeriodInfo
from delivery.email_sender import (
    EmailServiceConfig,
    build_email_message,
    save_dry_run_email,
    send_email_report,
)
from render.charts import GeneratedChart
from scoring.engine import Scorecard


@pytest.fixture
def mock_period() -> PeriodInfo:
    return PeriodInfo(
        report_type="daily",
        as_of_date="2026-10-22",
        session_date="2026-10-22",
        current_start="2026-10-22",
        current_end="2026-10-22",
        baseline_date="2026-10-21",
        prev_period_start="2026-10-21",
        prev_period_end="2026-10-21",
        prev_baseline_date="2026-10-20",
        is_partial=False,
        session_count=1,
    )


@pytest.fixture
def mock_scorecard() -> Scorecard:
    return Scorecard(
        raw_score=2.0,
        max_score=6.0,
        normalized_score=0.33,
        verdict="Bullish",
        votes=[],
        caution_flags=[],
        top_bullish_factors=["50 DMA > 200 DMA", "Breadth Expanding"],
        top_bearish_factors=["VIX Rising"],
        summary_reasons=["Overall market technical posture is Bullish."],
    )


def test_build_email_message_structure(mock_period, mock_scorecard, tmp_path):
    """Test MIME message building with plain-text fallback, CID inline images, and HTML attachment."""
    # Create a dummy chart
    dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    charts = {
        "spx_technicals": GeneratedChart(
            key="spx_technicals",
            title="S&P 500",
            caption="SPX Chart",
            base64_data=dummy_b64,
            is_available=True,
        )
    }

    dummy_html_file = tmp_path / "test_report.html"
    dummy_html_file.write_text("<html><body><h1>Market Report</h1></body></html>")

    msg = build_email_message(
        period=mock_period,
        scorecard=mock_scorecard,
        html_content="<html><body><img src=\"data:image/png;base64," + dummy_b64 + "\"></body></html>",
        md_content="# Daily Report",
        charts=charts,
        html_attachment_path=dummy_html_file,
        sender="sender@example.com",
        recipients=["trader1@example.com", "trader2@example.com"],
    )

    # Subject format: [Daily|Weekly|Monthly] Market Report - YYYY-MM-DD - {Bullish|Neutral|Bearish}
    assert msg["Subject"] == "[Daily] Market Report - 2026-10-22 - Bullish"
    assert msg["From"] == "sender@example.com"
    assert "trader1@example.com" in msg["To"]
    assert "trader2@example.com" in msg["To"]

    # Verify MIME hierarchy
    assert msg.is_multipart()
    assert msg.get_content_type() == "multipart/mixed"

    # Walk parts
    part_types = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in part_types
    assert "text/html" in part_types
    assert "image/png" in part_types
    assert "application/octet-stream" in part_types

    # Verify CID attachment
    image_parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(image_parts) == 1
    assert image_parts[0]["Content-ID"] == "<chart_spx_technicals>"


def test_save_dry_run_email(mock_period, mock_scorecard, tmp_path):
    """Test saving email message to .eml file."""
    msg = build_email_message(
        period=mock_period,
        scorecard=mock_scorecard,
        html_content="<html><body>Report</body></html>",
        md_content="Report",
        charts={},
    )

    eml_file = tmp_path / "test_email.eml"
    saved_path = save_dry_run_email(msg, eml_file)

    assert saved_path.exists()
    assert saved_path.stat().st_size > 0

    # Verify it can be parsed back as a standard email message
    with open(saved_path, "rb") as f:
        parsed_msg = email.message_from_binary_file(f)
    assert parsed_msg["Subject"] == "[Daily] Market Report - 2026-10-22 - Bullish"


def test_send_email_failure_handling(mock_period, mock_scorecard):
    """Test that failed SMTP connection returns (False, error) without raising an exception."""
    msg = build_email_message(
        period=mock_period,
        scorecard=mock_scorecard,
        html_content="<html><body>Report</body></html>",
        md_content="Report",
        charts={},
    )

    # Point to non-existent invalid SMTP server to test failure path
    bad_config = EmailServiceConfig(
        enabled=True,
        smtp_host="invalid-smtp-host.nonexistent.local",
        smtp_port=587,
        smtp_user="test",
        smtp_password="pwd",
        email_from="sender@example.com",
        email_to=["recipient@example.com"],
    )

    success, err_msg = send_email_report(msg, bad_config)
    assert success is False
    assert "Failed to send email" in err_msg
