from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class MGFormulaCandidateSpec:
    """Implementation-independent MG candidate formula definition.

    This object is intentionally limited to causal marker/state membership. It
    does not contain outcome labels, future bars, ticker/date exceptions, or
    backtest-only values. The same required/forbidden marker set can therefore
    be evaluated by Python and emitted as an AFL boolean expression.
    """

    formula_id: str
    required: tuple[str, ...]
    forbidden: tuple[str, ...] = ()
    first_match_per_ticker_day: bool = True
    status: str = "RESEARCH_CANDIDATE_NOT_CANONICAL"

    def validate(self) -> None:
        if not self.formula_id.strip():
            raise ValueError("FORMULA_ID_REQUIRED")
        if not self.required:
            raise ValueError("AT_LEAST_ONE_REQUIRED_MARKER")
        if len(set(self.required)) != len(self.required):
            raise ValueError("DUPLICATE_REQUIRED_MARKER")
        if len(set(self.forbidden)) != len(self.forbidden):
            raise ValueError("DUPLICATE_FORBIDDEN_MARKER")
        overlap = set(self.required) & set(self.forbidden)
        if overlap:
            raise ValueError(f"MARKER_REQUIRED_AND_FORBIDDEN:{','.join(sorted(overlap))}")

    def matches(self, markers: Iterable[str]) -> bool:
        self.validate()
        present = set(markers)
        return all(x in present for x in self.required) and not any(
            x in present for x in self.forbidden
        )

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "formula_id": self.formula_id,
            "required": list(self.required),
            "forbidden": list(self.forbidden),
            "first_match_per_ticker_day": self.first_match_per_ticker_day,
            "status": self.status,
            "future_data_used_for_formula_state": False,
        }


def _afl_name(marker: str) -> str:
    out = []
    for ch in marker.upper():
        out.append(ch if ch.isalnum() else "_")
    return "S_" + "".join(out)


def to_afl_boolean_expression(spec: MGFormulaCandidateSpec) -> str:
    """Emit an AFL boolean expression with one deterministic variable per marker.

    The caller must bind every emitted S_<MARKER> array to an AFL implementation
    that is parity-tested against the Python marker of the same name.
    """
    spec.validate()
    required = " AND ".join(_afl_name(x) for x in spec.required)
    forbidden = " AND ".join(f"NOT {_afl_name(x)}" for x in spec.forbidden)
    return f"({required})" if not forbidden else f"({required}) AND ({forbidden})"


def evaluate_first_matches(
    marker_rows: Sequence[Iterable[str]], spec: MGFormulaCandidateSpec
) -> tuple[bool, ...]:
    """Evaluate a chronological ticker-day path and enforce first-match semantics."""
    spec.validate()
    out: list[bool] = []
    already_matched = False
    for markers in marker_rows:
        matched = spec.matches(markers)
        if spec.first_match_per_ticker_day and already_matched:
            matched = False
        out.append(matched)
        already_matched = already_matched or matched
    return tuple(out)


def spec_from_v5_candidate(row: Mapping[str, object], *, formula_id: str) -> MGFormulaCandidateSpec:
    """Freeze one already-validated V5 signature into a reusable candidate spec.

    Only the causal signature parts are copied. Performance/outcome fields are
    deliberately excluded from the executable formula definition.
    """
    parts = row.get("parts")
    if not isinstance(parts, list) or not parts or not all(isinstance(x, str) for x in parts):
        raise ValueError("V5_CANDIDATE_PARTS_REQUIRED")
    spec = MGFormulaCandidateSpec(formula_id=formula_id, required=tuple(parts))
    spec.validate()
    return spec
