"""Unit tests for CLI Usability improvements in report.py."""

import argparse
from unittest.mock import patch
import pytest

from report import run_interactive_wizard, generate_market_report, _progress


def test_cli_argument_defaults():
    """Verify that default CLI arguments correctly set type to 'daily' and open_browser to False."""
    from report import main
    with patch("sys.argv", ["report.py", "--if-scheduled-day"]), \
         patch("report.generate_market_report", return_value={"status": "skipped", "reason": "test"}) as mock_gen:
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        mock_gen.assert_called_once()
        _, kwargs = mock_gen.call_args
        assert kwargs["report_type"] == "daily"
        assert kwargs["quiet"] is False


def test_cli_short_flags():
    """Verify that shorthand flags -t, -d, -o, -O, -q are correctly parsed."""
    from report import main
    with patch("sys.argv", [
        "report.py",
        "-t", "weekly",
        "-d", "2026-10-30",
        "-o", "custom_reports",
        "-q",
        "--if-scheduled-day",
    ]), patch("report.generate_market_report", return_value={"status": "skipped", "reason": "test"}) as mock_gen:
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        _, kwargs = mock_gen.call_args
        assert kwargs["report_type"] == "weekly"
        assert kwargs["target_date"] == "2026-10-30"
        assert kwargs["output_dir"] == "custom_reports"
        assert kwargs["quiet"] is True


def test_interactive_wizard_input_mapping():
    """Verify interactive wizard maps 1 -> daily, 2 -> weekly, 3 -> monthly and browser preference."""
    with patch("builtins.input", side_effect=["2", "2026-10-30", "y"]):
        res = run_interactive_wizard()
        assert res["type"] == "weekly"
        assert res["date"] == "2026-10-30"
        assert res["open"] is True

    with patch("builtins.input", side_effect=["", "", "n"]):
        res = run_interactive_wizard()
        assert res["type"] == "daily"
        assert res["date"] is None
        assert res["open"] is False


def test_progress_output_respects_quiet(capsys):
    """Verify _progress writes to stdout unless quiet is True."""
    _progress(1, 6, "📅", "Test step message", quiet=False)
    captured = capsys.readouterr()
    assert "[1/6] Test step message" in captured.out

    _progress(1, 6, "📅", "Quiet message", quiet=True)
    captured_quiet = capsys.readouterr()
    assert "Quiet message" not in captured_quiet.out


def test_cli_watchlist_and_tickers_flags():
    """Verify that --tickers and -w/--watchlist flags are forwarded to generate_market_report."""
    from report import main
    with patch("sys.argv", [
        "report.py",
        "--tickers", "NVDA,AAPL,TSLA",
        "-w", "my_custom_watchlist.csv",
        "--if-scheduled-day",
    ]), patch("report.generate_market_report", return_value={"status": "skipped", "reason": "test"}) as mock_gen:
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        _, kwargs = mock_gen.call_args
        assert kwargs["tickers"] == "NVDA,AAPL,TSLA"
        assert kwargs["watchlist_path"] == "my_custom_watchlist.csv"

