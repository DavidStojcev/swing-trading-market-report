"""Unit tests for SQLite snapshot persistence and comparison."""

import os
from pathlib import Path
import pytest
from storage.snapshots import SnapshotStore


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_snapshots.db"
    return SnapshotStore(db_path=str(db_file))


def test_save_and_retrieve_snapshot(temp_db):
    metrics = {
        "verdict": "Bullish",
        "score": 0.8,
        "vix": 16.5,
        "spx_close": 5850.25,
    }

    temp_db.save_snapshot("daily", "2026-10-22", metrics)
    retrieved = temp_db.get_snapshot("daily", "2026-10-22")

    assert retrieved is not None
    assert retrieved["verdict"] == "Bullish"
    assert retrieved["score"] == 0.8
    assert retrieved["vix"] == 16.5
    assert retrieved["spx_close"] == 5850.25


def test_prior_snapshot_lookup(temp_db):
    temp_db.save_snapshot("daily", "2026-10-20", {"spx_close": 5800.0})
    temp_db.save_snapshot("daily", "2026-10-21", {"spx_close": 5820.0})
    temp_db.save_snapshot("daily", "2026-10-22", {"spx_close": 5850.0})

    prior = temp_db.get_latest_prior_snapshot("daily", "2026-10-22")
    assert prior is not None
    assert prior["spx_close"] == 5820.0


def test_nonexistent_snapshot_returns_none(temp_db):
    res = temp_db.get_snapshot("daily", "1999-01-01")
    assert res is None
