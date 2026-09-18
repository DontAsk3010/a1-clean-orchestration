import sqlite3

from a1clean.formula_research.full_chronological_cache_catalog import (
    FULL_CHRONOLOGICAL_SOURCE_NAMES,
    MARCH_2025_SOURCE,
)
from a1clean.formula_research.v31_full_chronological_semantic_enrichment import (
    SCHEMA,
    _carry_for_full,
    _indexed_source_bounds,
    _rewrite_lineage,
)


def test_full_chronological_source_order_includes_march_between_feb_and_april():
    names = list(FULL_CHRONOLOGICAL_SOURCE_NAMES)
    feb = names.index("Raw Feb 03-28-2025.csv")
    march = names.index(MARCH_2025_SOURCE)
    april = names.index("Raw April 01-30-2025.csv")
    assert feb + 1 == march
    assert march + 1 == april
    assert len(names) == 18
    assert len(set(names)) == 18


def test_full_carry_uses_previous_governed_march_day_for_april():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE days(source_order INTEGER, source TEXT, ticker TEXT, day TEXT, "
        "bar_count INTEGER, first_timestamp TEXT, last_timestamp TEXT, final_close REAL)"
    )
    db.execute("CREATE TABLE calendar(day TEXT PRIMARY KEY, previous_day TEXT)")
    db.execute("INSERT INTO calendar VALUES(?,?)", ("2025-04-08", "2025-03-27"))
    db.execute(
        "INSERT INTO days VALUES(?,?,?,?,?,?,?,?)",
        (
            3,
            MARCH_2025_SOURCE,
            "AAAA",
            "2025-03-27",
            100,
            "2025-03-27T09:00:00",
            "2025-03-27T16:00:00",
            123.0,
        ),
    )
    carry, prev = _carry_for_full(db, ticker="AAAA", day="2025-04-08")
    assert prev == "2025-03-27"
    assert carry is not None
    assert carry["status"] == "EXACT_PREVIOUS_GOVERNED_DATE_PACKET"
    assert carry["source"] == MARCH_2025_SOURCE


def test_indexed_source_bounds_use_actual_packet_dates_not_filename_envelope():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE days(source_order INTEGER, source TEXT, ticker TEXT, day TEXT, "
        "bar_count INTEGER, first_timestamp TEXT, last_timestamp TEXT, final_close REAL)"
    )
    db.executemany(
        "INSERT INTO days VALUES(?,?,?,?,?,?,?,?)",
        [
            (3, MARCH_2025_SOURCE, "AAAA", "2025-03-03", 10, None, None, 100.0),
            (3, MARCH_2025_SOURCE, "BBBB", "2025-03-27", 10, None, None, 101.0),
            (4, "Raw April 01-30-2025.csv", "AAAA", "2025-04-08", 10, None, None, 102.0),
            (4, "Raw April 01-30-2025.csv", "BBBB", "2025-04-30", 10, None, None, 103.0),
        ],
    )
    assert _indexed_source_bounds(db, MARCH_2025_SOURCE) == ("2025-03-03", "2025-03-27")
    assert _indexed_source_bounds(db, "Raw April 01-30-2025.csv") == ("2025-04-08", "2025-04-30")


def test_v31_lineage_overrides_failed_v30_output_schema():
    rec = _rewrite_lineage({"schema": "A1_V30_SEMANTIC_JOURNEY_ENRICHMENT_V1", "x": 1})
    assert rec["schema"] == SCHEMA
    assert rec["semantic_engine_parent_schema"] == "A1_V30_SEMANTIC_JOURNEY_ENRICHMENT_V1"
    assert rec["lineage_version"] == "V3.1_FULL_CHRONOLOGICAL"
