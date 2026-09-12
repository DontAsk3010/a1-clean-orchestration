from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from ..config import CANONICAL_CURRENT_FOLDER_NAME, FROZEN_CURRENT_FOLDER_DRIVE_ID
from ..source_parity import FOLDER_MIME, _assert_folder, _download_bytes, _list_children
from .contracts import PatternDiscoveryContractError, fingerprint
from .packet import ParsedTickerDayPacket, parse_semantic_packet


@dataclass(frozen=True)
class SourceEnvelopeIdentity:
    source_name: str
    source_drive_id: str
    source_sha256: str
    generation_id: str
    data_plane_manifest_file_id: str
    semantic_manifest_file_id: str
    semantic_manifest_fingerprint: str
    ticker_day_count: int
    source_data_rows: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_drive_id": self.source_drive_id,
            "source_sha256": self.source_sha256,
            "generation_id": self.generation_id,
            "data_plane_manifest_file_id": self.data_plane_manifest_file_id,
            "semantic_manifest_file_id": self.semantic_manifest_file_id,
            "semantic_manifest_fingerprint": self.semantic_manifest_fingerprint,
            "ticker_day_count": self.ticker_day_count,
            "source_data_rows": self.source_data_rows,
        }


@dataclass(frozen=True)
class SemanticManifestRow:
    manifest_index: int
    trading_date: str
    ticker: str
    bundle_name: str
    bundle_line_number: int
    data_row_count: int
    first_clock_time: str
    last_clock_time: str
    source_row_first: int
    source_row_last: int

    @classmethod
    def from_mapping(cls, manifest_index: int, row: Mapping[str, Any]) -> "SemanticManifestRow":
        required = (
            "trading_date",
            "ticker",
            "bundle_name",
            "bundle_line_number",
            "data_row_count",
            "first_clock_time",
            "last_clock_time",
            "source_row_first",
            "source_row_last",
        )
        missing = [key for key in required if key not in row]
        if missing:
            raise PatternDiscoveryContractError(
                f"SEMANTIC_MANIFEST_REQUIRED_FIELDS_MISSING:INDEX={manifest_index}:{missing}"
            )
        return cls(
            manifest_index=manifest_index,
            trading_date=str(row["trading_date"]),
            ticker=str(row["ticker"]),
            bundle_name=str(row["bundle_name"]),
            bundle_line_number=int(row["bundle_line_number"]),
            data_row_count=int(row["data_row_count"]),
            first_clock_time=str(row["first_clock_time"]),
            last_clock_time=str(row["last_clock_time"]),
            source_row_first=int(row["source_row_first"]),
            source_row_last=int(row["source_row_last"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_index": self.manifest_index,
            "trading_date": self.trading_date,
            "ticker": self.ticker,
            "bundle_name": self.bundle_name,
            "bundle_line_number": self.bundle_line_number,
            "data_row_count": self.data_row_count,
            "first_clock_time": self.first_clock_time,
            "last_clock_time": self.last_clock_time,
            "source_row_first": self.source_row_first,
            "source_row_last": self.source_row_last,
        }


class GovernedSourceReader:
    def __init__(self, reader_api, *, source_name: str):
        self.api = reader_api
        self.source_name = source_name
        self.stem = Path(source_name).stem
        _assert_folder(self.api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
        root_children = _list_children(self.api, FROZEN_CURRENT_FOLDER_DRIVE_ID)
        folder_map = {
            str(item["name"]): item
            for item in root_children
            if item.get("mimeType") == FOLDER_MIME
        }
        for required in ("00_MANIFESTS", "02_SEMANTIC_BUNDLES"):
            if required not in folder_map:
                raise PatternDiscoveryContractError(f"CURRENT_REQUIRED_FOLDER_MISSING:{required}")
        self.manifest_folder_id = str(folder_map["00_MANIFESTS"]["id"])
        self.bundle_folder_id = str(folder_map["02_SEMANTIC_BUNDLES"]["id"])

        manifest_children = _list_children(self.api, self.manifest_folder_id)
        self.data_plane_manifest_item = self._exact_named(
            manifest_children, f"{self.stem}__DATA_PLANE_MANIFEST.json"
        )
        self.semantic_manifest_item = self._exact_named(
            manifest_children, f"{self.stem}__SEMANTIC_BUNDLES_MANIFEST.json"
        )
        self.data_plane_manifest = self._download_json(self.data_plane_manifest_item)
        semantic_manifest_bytes = _download_bytes(self.api, str(self.semantic_manifest_item["id"]))
        try:
            semantic_manifest_obj = json.loads(semantic_manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PatternDiscoveryContractError("SEMANTIC_MANIFEST_NOT_VALID_UTF8_JSON") from exc
        if not isinstance(semantic_manifest_obj, list):
            raise PatternDiscoveryContractError("SEMANTIC_MANIFEST_NOT_LIST")
        self.semantic_manifest_raw = semantic_manifest_obj
        self.semantic_manifest_rows = tuple(
            SemanticManifestRow.from_mapping(idx, row)
            for idx, row in enumerate(semantic_manifest_obj)
        )
        self.semantic_manifest_fingerprint = hashlib.sha256(semantic_manifest_bytes).hexdigest()
        self._validate_data_plane_manifest()

        bundle_children = _list_children(self.api, self.bundle_folder_id)
        self.bundle_items = {
            str(item["name"]): item
            for item in bundle_children
            if item.get("mimeType") != FOLDER_MIME
            and str(item.get("name") or "").startswith(f"{self.stem}__SEMANTIC_")
            and str(item.get("name") or "").endswith(".jsonl")
        }
        required_bundle_names = {row.bundle_name for row in self.semantic_manifest_rows}
        missing_bundles = sorted(required_bundle_names - set(self.bundle_items))
        if missing_bundles:
            raise PatternDiscoveryContractError(
                f"SEMANTIC_BUNDLE_FILES_MISSING:COUNT={len(missing_bundles)}:FIRST={missing_bundles[:3]}"
            )
        extra_bundles = sorted(set(self.bundle_items) - required_bundle_names)
        if extra_bundles:
            raise PatternDiscoveryContractError(
                f"SEMANTIC_BUNDLE_FILES_UNREFERENCED:COUNT={len(extra_bundles)}:FIRST={extra_bundles[:3]}"
            )
        self._cached_bundle_name: str | None = None
        self._cached_bundle_lines: tuple[str, ...] = ()

    @staticmethod
    def _exact_named(items: list[dict], name: str) -> dict:
        matches = [item for item in items if item.get("name") == name and item.get("mimeType") != FOLDER_MIME]
        if len(matches) != 1:
            raise PatternDiscoveryContractError(f"CURRENT_FILE_CARDINALITY:{name}:{len(matches)}")
        return matches[0]

    def _download_json(self, item: Mapping[str, Any]) -> dict[str, Any]:
        data = _download_bytes(self.api, str(item["id"]))
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PatternDiscoveryContractError(f"CURRENT_JSON_INVALID:{item.get('name')}") from exc
        if not isinstance(obj, dict):
            raise PatternDiscoveryContractError(f"CURRENT_JSON_NOT_OBJECT:{item.get('name')}")
        return obj

    def _validate_data_plane_manifest(self) -> None:
        obj = self.data_plane_manifest
        if obj.get("source_name") != self.source_name:
            raise PatternDiscoveryContractError(
                f"SOURCE_NAME_MANIFEST_MISMATCH:REQUESTED={self.source_name}:MANIFEST={obj.get('source_name')}"
            )
        if obj.get("status") != "ACCESS_READY_FOR_AI":
            raise PatternDiscoveryContractError(f"SOURCE_NOT_GOVERNED_READY:{obj.get('status')}")
        if not obj.get("physical_access_ready"):
            raise PatternDiscoveryContractError("SOURCE_PHYSICAL_ACCESS_NOT_READY")
        if obj.get("sampling_used") is not False or obj.get("filtering_used") is not False:
            raise PatternDiscoveryContractError("SOURCE_DATA_PLANE_SAMPLING_OR_FILTERING_DETECTED")
        if obj.get("behavior_labels_created") is not False:
            raise PatternDiscoveryContractError("SOURCE_DATA_PLANE_BEHAVIOR_LABELS_DETECTED")
        if not obj.get("all_fields_preserved"):
            raise PatternDiscoveryContractError("SOURCE_DATA_PLANE_NOT_ALL_FIELDS_PRESERVED")
        ticker_day_objects = int(obj.get("ticker_day_objects") or -1)
        source_data_rows = int(obj.get("source_data_rows") or -1)
        if ticker_day_objects != len(self.semantic_manifest_rows):
            raise PatternDiscoveryContractError(
                f"SEMANTIC_MANIFEST_COUNT_MISMATCH:DATA_PLANE={ticker_day_objects}:MANIFEST={len(self.semantic_manifest_rows)}"
            )
        manifest_rows = sum(row.data_row_count for row in self.semantic_manifest_rows)
        if manifest_rows != source_data_rows:
            raise PatternDiscoveryContractError(
                f"SEMANTIC_MANIFEST_ROW_SUM_MISMATCH:DATA_PLANE={source_data_rows}:MANIFEST={manifest_rows}"
            )

    @property
    def identity(self) -> SourceEnvelopeIdentity:
        obj = self.data_plane_manifest
        return SourceEnvelopeIdentity(
            source_name=self.source_name,
            source_drive_id=str(obj["source_drive_id"]),
            source_sha256=str(obj["source_sha256"]),
            generation_id=str(obj["generation_id"]),
            data_plane_manifest_file_id=str(self.data_plane_manifest_item["id"]),
            semantic_manifest_file_id=str(self.semantic_manifest_item["id"]),
            semantic_manifest_fingerprint=self.semantic_manifest_fingerprint,
            ticker_day_count=len(self.semantic_manifest_rows),
            source_data_rows=int(obj["source_data_rows"]),
        )

    def _bundle_lines(self, bundle_name: str) -> tuple[str, ...]:
        if self._cached_bundle_name == bundle_name:
            return self._cached_bundle_lines
        item = self.bundle_items.get(bundle_name)
        if item is None:
            raise PatternDiscoveryContractError(f"SEMANTIC_BUNDLE_NOT_FOUND:{bundle_name}")
        data = _download_bytes(self.api, str(item["id"]))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PatternDiscoveryContractError(f"SEMANTIC_BUNDLE_NOT_UTF8:{bundle_name}") from exc
        lines = tuple(text.splitlines())
        self._cached_bundle_name = bundle_name
        self._cached_bundle_lines = lines
        return lines

    def load_packet(self, manifest_index: int) -> ParsedTickerDayPacket:
        if manifest_index < 0 or manifest_index >= len(self.semantic_manifest_rows):
            raise PatternDiscoveryContractError(
                f"SEMANTIC_MANIFEST_INDEX_OUT_OF_RANGE:{manifest_index}:{len(self.semantic_manifest_rows)}"
            )
        ref = self.semantic_manifest_rows[manifest_index]
        lines = self._bundle_lines(ref.bundle_name)
        line_idx = ref.bundle_line_number - 1
        if line_idx < 0 or line_idx >= len(lines):
            raise PatternDiscoveryContractError(
                f"SEMANTIC_BUNDLE_LINE_OUT_OF_RANGE:{ref.bundle_name}:{ref.bundle_line_number}:{len(lines)}"
            )
        try:
            obj = json.loads(lines[line_idx])
        except json.JSONDecodeError as exc:
            raise PatternDiscoveryContractError(
                f"SEMANTIC_BUNDLE_LINE_JSON_INVALID:{ref.bundle_name}:{ref.bundle_line_number}"
            ) from exc
        if not isinstance(obj, dict):
            raise PatternDiscoveryContractError(
                f"SEMANTIC_BUNDLE_LINE_NOT_OBJECT:{ref.bundle_name}:{ref.bundle_line_number}"
            )
        packet = parse_semantic_packet(obj)
        expected_identity = {
            "generation_id": self.identity.generation_id,
            "source_drive_id": self.identity.source_drive_id,
            "source_name": self.identity.source_name,
            "source_sha256": self.identity.source_sha256,
            "trading_date": ref.trading_date,
            "ticker": ref.ticker,
            "first_clock_time": ref.first_clock_time,
            "last_clock_time": ref.last_clock_time,
            "data_row_count": ref.data_row_count,
            "source_row_first": ref.source_row_first,
            "source_row_last": ref.source_row_last,
        }
        if packet.identity.as_dict() != expected_identity:
            raise PatternDiscoveryContractError(
                "SEMANTIC_PACKET_MANIFEST_IDENTITY_MISMATCH:"
                f"INDEX={manifest_index}:EXPECTED_FP={fingerprint(expected_identity)}:"
                f"ACTUAL_FP={fingerprint(packet.identity.as_dict())}"
            )
        return packet

    def iter_packets(self, *, start_index: int = 0) -> Iterator[tuple[SemanticManifestRow, ParsedTickerDayPacket]]:
        for idx in range(start_index, len(self.semantic_manifest_rows)):
            yield self.semantic_manifest_rows[idx], self.load_packet(idx)
