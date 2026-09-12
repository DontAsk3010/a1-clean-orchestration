from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

LANE_ID = "A1_ALGORITHMIC_PATTERN_DISCOVERY_V1"


class PatternDiscoveryContractError(ValueError):
    """Fail-closed contract violation for the independent algorithmic lane."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TickerDayIdentity:
    generation_id: str
    source_drive_id: str
    source_name: str
    source_sha256: str
    trading_date: str
    ticker: str
    first_clock_time: str
    last_clock_time: str
    data_row_count: int
    source_row_first: int
    source_row_last: int

    @classmethod
    def from_semantic_packet(cls, obj: Mapping[str, Any]) -> "TickerDayIdentity":
        required = (
            "generation_id",
            "source_drive_id",
            "source_name",
            "source_sha256",
            "trading_date",
            "ticker",
            "first_clock_time",
            "last_clock_time",
            "data_row_count",
            "source_row_first",
            "source_row_last",
        )
        missing = [key for key in required if key not in obj]
        if missing:
            raise PatternDiscoveryContractError(f"IDENTITY_REQUIRED_FIELDS_MISSING:{missing}")
        return cls(**{key: obj[key] for key in required})

    def as_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "source_drive_id": self.source_drive_id,
            "source_name": self.source_name,
            "source_sha256": self.source_sha256,
            "trading_date": self.trading_date,
            "ticker": self.ticker,
            "first_clock_time": self.first_clock_time,
            "last_clock_time": self.last_clock_time,
            "data_row_count": self.data_row_count,
            "source_row_first": self.source_row_first,
            "source_row_last": self.source_row_last,
        }


@dataclass(frozen=True)
class RupturesRunSpec:
    run_id: str
    field: str
    algorithm: str
    model: str
    predict_kwargs: Mapping[str, Any]
    algorithm_kwargs: Mapping[str, Any]


@dataclass(frozen=True)
class StumpyRunSpec:
    run_id: str
    field: str
    window: int


@dataclass(frozen=True)
class DtwRunSpec:
    run_id: str
    left_field: str
    right_field: str


@dataclass(frozen=True)
class DiscoveryPlan:
    plan_id: str
    ruptures: tuple[RupturesRunSpec, ...]
    stumpy: tuple[StumpyRunSpec, ...]
    dtw: tuple[DtwRunSpec, ...]

    @classmethod
    def from_dict(cls, obj: Mapping[str, Any]) -> "DiscoveryPlan":
        allowed = {"plan_id", "ruptures", "stumpy", "dtw"}
        unknown = sorted(set(obj) - allowed)
        if unknown:
            raise PatternDiscoveryContractError(f"DISCOVERY_PLAN_UNKNOWN_KEYS:{unknown}")
        plan_id = str(obj.get("plan_id") or "").strip()
        if not plan_id:
            raise PatternDiscoveryContractError("DISCOVERY_PLAN_ID_REQUIRED")

        ruptures_specs: list[RupturesRunSpec] = []
        for row in obj.get("ruptures", []) or []:
            required = {"run_id", "field", "algorithm", "model", "predict_kwargs"}
            missing = sorted(required - set(row))
            unknown_row = sorted(set(row) - (required | {"algorithm_kwargs"}))
            if missing:
                raise PatternDiscoveryContractError(f"RUPTURES_SPEC_MISSING:{missing}")
            if unknown_row:
                raise PatternDiscoveryContractError(f"RUPTURES_SPEC_UNKNOWN:{unknown_row}")
            if not isinstance(row["predict_kwargs"], Mapping) or not row["predict_kwargs"]:
                raise PatternDiscoveryContractError("RUPTURES_PREDICT_KWARGS_REQUIRED")
            algorithm_kwargs = row.get("algorithm_kwargs", {})
            if not isinstance(algorithm_kwargs, Mapping):
                raise PatternDiscoveryContractError("RUPTURES_ALGORITHM_KWARGS_NOT_MAPPING")
            ruptures_specs.append(
                RupturesRunSpec(
                    run_id=str(row["run_id"]),
                    field=str(row["field"]),
                    algorithm=str(row["algorithm"]),
                    model=str(row["model"]),
                    predict_kwargs=dict(row["predict_kwargs"]),
                    algorithm_kwargs=dict(algorithm_kwargs),
                )
            )

        stumpy_specs: list[StumpyRunSpec] = []
        for row in obj.get("stumpy", []) or []:
            required = {"run_id", "field", "window"}
            missing = sorted(required - set(row))
            unknown_row = sorted(set(row) - required)
            if missing:
                raise PatternDiscoveryContractError(f"STUMPY_SPEC_MISSING:{missing}")
            if unknown_row:
                raise PatternDiscoveryContractError(f"STUMPY_SPEC_UNKNOWN:{unknown_row}")
            window = int(row["window"])
            if window < 3:
                raise PatternDiscoveryContractError("STUMPY_WINDOW_LT_3")
            stumpy_specs.append(
                StumpyRunSpec(run_id=str(row["run_id"]), field=str(row["field"]), window=window)
            )

        dtw_specs: list[DtwRunSpec] = []
        for row in obj.get("dtw", []) or []:
            required = {"run_id", "left_field", "right_field"}
            missing = sorted(required - set(row))
            unknown_row = sorted(set(row) - required)
            if missing:
                raise PatternDiscoveryContractError(f"DTW_SPEC_MISSING:{missing}")
            if unknown_row:
                raise PatternDiscoveryContractError(f"DTW_SPEC_UNKNOWN:{unknown_row}")
            dtw_specs.append(
                DtwRunSpec(
                    run_id=str(row["run_id"]),
                    left_field=str(row["left_field"]),
                    right_field=str(row["right_field"]),
                )
            )

        all_ids = [x.run_id for x in ruptures_specs] + [x.run_id for x in stumpy_specs] + [x.run_id for x in dtw_specs]
        if len(all_ids) != len(set(all_ids)):
            raise PatternDiscoveryContractError("DISCOVERY_RUN_ID_DUPLICATE")
        if not all_ids:
            raise PatternDiscoveryContractError("DISCOVERY_PLAN_EMPTY")

        return cls(
            plan_id=plan_id,
            ruptures=tuple(ruptures_specs),
            stumpy=tuple(stumpy_specs),
            dtw=tuple(dtw_specs),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "ruptures": [
                {
                    "run_id": row.run_id,
                    "field": row.field,
                    "algorithm": row.algorithm,
                    "model": row.model,
                    "predict_kwargs": dict(row.predict_kwargs),
                    "algorithm_kwargs": dict(row.algorithm_kwargs),
                }
                for row in self.ruptures
            ],
            "stumpy": [
                {"run_id": row.run_id, "field": row.field, "window": row.window}
                for row in self.stumpy
            ],
            "dtw": [
                {"run_id": row.run_id, "left_field": row.left_field, "right_field": row.right_field}
                for row in self.dtw
            ],
        }

    @property
    def sha256(self) -> str:
        return fingerprint(self.as_dict())
