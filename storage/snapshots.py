"""Snapshot persistence in SQLite for period-over-period delta comparisons."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SnapshotStore:
    """Manages local SQLite storage of report metrics for delta comparisons."""

    def __init__(self, db_path: str = ".cache/snapshots.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        """Initialize SQLite table schema."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS report_snapshots (
                        report_type TEXT NOT NULL,
                        period_date TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        metrics_json TEXT NOT NULL,
                        PRIMARY KEY (report_type, period_date)
                    )
                    """
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to initialize snapshot database: %s", e)

    def save_snapshot(
        self,
        report_type: str,
        period_date: str,
        metrics: Dict[str, Any],
    ) -> None:
        """Save or overwrite a metric snapshot for a report type and period date."""
        try:
            created_at = datetime.now(timezone.utc).isoformat()
            data_str = json.dumps(metrics)
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO report_snapshots (report_type, period_date, created_at, metrics_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(report_type, period_date) DO UPDATE SET
                        created_at = excluded.created_at,
                        metrics_json = excluded.metrics_json
                    """,
                    (report_type.lower(), period_date, created_at, data_str),
                )
                conn.commit()
            logger.debug("Saved snapshot for %s / %s", report_type, period_date)
        except Exception as e:
            logger.warning("Error saving snapshot for %s / %s: %s", report_type, period_date, e)

    def get_snapshot(
        self,
        report_type: str,
        period_date: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a specific snapshot by report type and period date."""
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT metrics_json FROM report_snapshots
                    WHERE report_type = ? AND period_date = ?
                    """,
                    (report_type.lower(), period_date),
                )
                row = cur.fetchone()
                if row:
                    return json.loads(row[0])
        except Exception as e:
            logger.warning("Error loading snapshot: %s", e)
        return None

    def get_latest_prior_snapshot(
        self,
        report_type: str,
        before_date: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent snapshot strictly before a given date."""
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT metrics_json FROM report_snapshots
                    WHERE report_type = ? AND period_date < ?
                    ORDER BY period_date DESC
                    LIMIT 1
                    """,
                    (report_type.lower(), before_date),
                )
                row = cur.fetchone()
                if row:
                    return json.loads(row[0])
        except Exception as e:
            logger.warning("Error loading prior snapshot: %s", e)
        return None
