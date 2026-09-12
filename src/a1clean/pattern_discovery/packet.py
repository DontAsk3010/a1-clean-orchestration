from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import io
import math
from typing import Any, Iterable, Mapping, Sequence

from .contracts import PatternDiscoveryContractError, TickerDayIdentity, fingerprint


@dataclass(frozen=True)
class ParsedTickerDayPacket:
    identity: TickerDayIdentity
    header: tuple[str, ...]
    rows: tuple[Mapping[str, str], ...]
    timestamps: tuple[datetime, ...]
    source_rows: tuple[int, ...]
    packet_fingerprint: str

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def numeric_series(self, field: str) -> tuple[float, ...]:
        if field not in self.header:
            raise PatternDiscoveryContractError(f"REQUESTED_FIELD_NOT_FOUND:{field}")
        values: list[float] = []
        for idx, row in enumerate(self.rows):
            raw = row.get(field)
            if raw is None or str(raw).strip() == "":
                raise PatternDiscoveryContractError(
                    f"REQUESTED_FIELD_MISSING_VALUE:{field}:INDEX={idx}:SOURCE_ROW={self.source_rows[idx]}"
                )
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise PatternDiscoveryContractError(
                    f"REQUESTED_FIELD_NON_NUMERIC:{field}:INDEX={idx}:SOURCE_ROW={self.source_rows[idx]}:VALUE={raw!r}"
                ) from exc
            if not math.isfinite(value):
                raise PatternDiscoveryContractError(
                    f"REQUESTED_FIELD_NON_FINITE:{field}:INDEX={idx}:SOURCE_ROW={self.source_rows[idx]}"
                )
            values.append(value)
        return tuple(values)

    def point_ref(self, index: int) -> dict[str, Any]:
        if index < 0 or index >= self.row_count:
            raise PatternDiscoveryContractError(f"POINT_INDEX_OUT_OF_RANGE:{index}:{self.row_count}")
        return {
            "index": index,
            "source_row": self.source_rows[index],
            "timestamp": self.timestamps[index].isoformat(sep=" "),
            "clock_time": self.timestamps[index].strftime("%H:%M:%S"),
        }

    def range_ref(self, start_index: int, end_index_inclusive: int) -> dict[str, Any]:
        if start_index < 0 or end_index_inclusive < start_index or end_index_inclusive >= self.row_count:
            raise PatternDiscoveryContractError(
                f"RANGE_INDEX_INVALID:{start_index}:{end_index_inclusive}:{self.row_count}"
            )
        return {
            "start": self.point_ref(start_index),
            "end": self.point_ref(end_index_inclusive),
            "length": end_index_inclusive - start_index + 1,
        }


def _parse_csv_record(text: str) -> list[str]:
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = list(reader)
    if len(rows) != 1:
        raise PatternDiscoveryContractError(f"PACKET_CSV_RECORD_CARDINALITY:{len(rows)}")
    return rows[0]


def _expand_source_rows(segments: Iterable[Sequence[int]]) -> tuple[int, ...]:
    out: list[int] = []
    previous_end: int | None = None
    for pos, segment in enumerate(segments):
        if len(segment) != 2:
            raise PatternDiscoveryContractError(f"SOURCE_ROW_SEGMENT_INVALID:{pos}:{segment}")
        first, last = int(segment[0]), int(segment[1])
        if first <= 0 or last < first:
            raise PatternDiscoveryContractError(f"SOURCE_ROW_SEGMENT_RANGE_INVALID:{pos}:{first}:{last}")
        if previous_end is not None and first <= previous_end:
            raise PatternDiscoveryContractError(
                f"SOURCE_ROW_SEGMENT_OVERLAP_OR_ORDER:{pos}:PREV_END={previous_end}:FIRST={first}"
            )
        out.extend(range(first, last + 1))
        previous_end = last
    return tuple(out)


def _parse_datetime(text: str) -> datetime:
    normalized = text.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PatternDiscoveryContractError(f"RAW_DATETIME_ISO_INVALID:{text!r}") from exc


def parse_semantic_packet(obj: Mapping[str, Any]) -> ParsedTickerDayPacket:
    identity = TickerDayIdentity.from_semantic_packet(obj)
    if not bool(obj.get("all_source_columns_retained")):
        raise PatternDiscoveryContractError("PACKET_NOT_ALL_SOURCE_COLUMNS_RETAINED")

    header_text = obj.get("raw_header")
    raw_rows_obj = obj.get("raw_rows")
    segments_obj = obj.get("source_row_segments")
    if not isinstance(header_text, str) or not header_text.strip():
        raise PatternDiscoveryContractError("RAW_HEADER_REQUIRED")
    if not isinstance(raw_rows_obj, list):
        raise PatternDiscoveryContractError("RAW_ROWS_LIST_REQUIRED")
    if not isinstance(segments_obj, list):
        raise PatternDiscoveryContractError("SOURCE_ROW_SEGMENTS_REQUIRED")

    header = tuple(_parse_csv_record(header_text))
    if not header or len(header) != len(set(header)):
        raise PatternDiscoveryContractError("RAW_HEADER_EMPTY_OR_DUPLICATE")
    required_columns = {"RAW_TICKER", "RAW_DATETIME_ISO"}
    missing_required = sorted(required_columns - set(header))
    if missing_required:
        raise PatternDiscoveryContractError(f"PACKET_REQUIRED_COLUMNS_MISSING:{missing_required}")

    source_rows = _expand_source_rows(segments_obj)
    expected = int(identity.data_row_count)
    if len(raw_rows_obj) != expected:
        raise PatternDiscoveryContractError(
            f"DATA_ROW_COUNT_MISMATCH:IDENTITY={expected}:RAW_ROWS={len(raw_rows_obj)}"
        )
    if len(source_rows) != expected:
        raise PatternDiscoveryContractError(
            f"SOURCE_ROW_SEGMENTS_COUNT_MISMATCH:IDENTITY={expected}:EXPANDED={len(source_rows)}"
        )
    if expected <= 0:
        raise PatternDiscoveryContractError("PACKET_EMPTY")
    if source_rows[0] != int(identity.source_row_first) or source_rows[-1] != int(identity.source_row_last):
        raise PatternDiscoveryContractError(
            "SOURCE_ROW_BOUNDARY_MISMATCH:"
            f"IDENTITY={identity.source_row_first}-{identity.source_row_last}:"
            f"EXPANDED={source_rows[0]}-{source_rows[-1]}"
        )

    parsed_rows: list[Mapping[str, str]] = []
    timestamps: list[datetime] = []
    previous_ts: datetime | None = None
    for idx, raw_text in enumerate(raw_rows_obj):
        if not isinstance(raw_text, str):
            raise PatternDiscoveryContractError(f"RAW_ROW_NOT_STRING:INDEX={idx}")
        values = _parse_csv_record(raw_text)
        if len(values) != len(header):
            raise PatternDiscoveryContractError(
                f"RAW_ROW_COLUMN_COUNT_MISMATCH:INDEX={idx}:EXPECTED={len(header)}:ACTUAL={len(values)}"
            )
        row = dict(zip(header, values, strict=True))
        if row["RAW_TICKER"] != identity.ticker:
            raise PatternDiscoveryContractError(
                f"RAW_TICKER_IDENTITY_MISMATCH:INDEX={idx}:IDENTITY={identity.ticker}:ROW={row['RAW_TICKER']}"
            )
        ts = _parse_datetime(row["RAW_DATETIME_ISO"])
        if ts.date().isoformat() != identity.trading_date:
            raise PatternDiscoveryContractError(
                f"RAW_TRADING_DATE_IDENTITY_MISMATCH:INDEX={idx}:IDENTITY={identity.trading_date}:ROW={ts.date().isoformat()}"
            )
        if previous_ts is not None and ts <= previous_ts:
            raise PatternDiscoveryContractError(
                f"RAW_TIME_DUPLICATE_OR_OUT_OF_ORDER:INDEX={idx}:PREV={previous_ts.isoformat()}:CURRENT={ts.isoformat()}"
            )
        previous_ts = ts
        parsed_rows.append(row)
        timestamps.append(ts)

    first_clock = timestamps[0].strftime("%H:%M:%S")
    last_clock = timestamps[-1].strftime("%H:%M:%S")
    if first_clock != identity.first_clock_time or last_clock != identity.last_clock_time:
        raise PatternDiscoveryContractError(
            "CLOCK_BOUNDARY_MISMATCH:"
            f"IDENTITY={identity.first_clock_time}-{identity.last_clock_time}:"
            f"ROWS={first_clock}-{last_clock}"
        )

    packet_fingerprint = fingerprint(
        {
            "identity": identity.as_dict(),
            "source_row_segments": segments_obj,
            "raw_header": header_text,
            "raw_rows": raw_rows_obj,
        }
    )
    return ParsedTickerDayPacket(
        identity=identity,
        header=header,
        rows=tuple(parsed_rows),
        timestamps=tuple(timestamps),
        source_rows=source_rows,
        packet_fingerprint=packet_fingerprint,
    )
