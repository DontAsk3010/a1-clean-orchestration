from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from typing import Any

ALLOWED_REPAIR_PATHS = (
    "src/a1clean/google_drive.py",
    "src/a1clean/pattern_discovery/drive_store.py",
    "src/a1clean/pattern_discovery/resilience.py",
    "src/a1clean/pattern_discovery/auto_continue.py",
)

AUTO_CONTINUE_REQUIRED_ANCHORS = (
    "FINAL_VERIFIED_PASS_ONLY_THEN_NEXT_CHRONOLOGICAL_MANIFEST_DATE",
    "GOVERNED_SEMANTIC_MANIFEST_NOT_CALENDAR_PLUS_ONE",
    "PASS_COMPLETE_GOVERNED_SCOPE_DISCOVERY_EVIDENCE",
    "find_verified_pass_checkpoint",
    "next_trading_date_scope",
)

HARD_HOLD_MARKERS = (
    "SOURCE_SHA256_MISMATCH",
    "PLAN_FINGERPRINT_MISMATCH",
    "SOURCE_DRIVE_ID_MISMATCH",
    "AUTO_CONTINUATION_PASS_GATE_FAILED",
    "SEMANTIC_PACKET_MANIFEST_IDENTITY_MISMATCH",
    "SOURCE_DATA_PLANE_SAMPLING_OR_FILTERING_DETECTED",
    "SOURCE_DATA_PLANE_BEHAVIOR_LABELS_DETECTED",
)

FORBIDDEN_ANALYTICAL_TERMS = (
    "ruptures",
    "stumpy",
    "dtw_tslearn",
    "buy_ready",
    "sell_signal",
    "tp-1",
    "tp-2",
)

SELF_HEAL_CACHE_SCHEMA = "A1_LANE2_SELF_HEAL_CALL_CACHE_V1"
MAX_MODEL_CALLS_PER_WORKFLOW = 2
MODEL_TRANSPORT_MAX_ATTEMPTS = 3
MODEL_RETRYABLE_HTTP = frozenset({408, 429, 500, 502, 503, 504})


def redact_secrets(text: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED_OPENAI_KEY]", text)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer [REDACTED]", text)
    return text


def hard_hold_reason(log_text: str) -> str | None:
    upper = log_text.upper()
    for marker in HARD_HOLD_MARKERS:
        if marker in upper:
            return f"GOVERNED_IDENTITY_OR_PASS_GATE:{marker}"
    return None


def failure_fingerprint(log_text: str) -> str:
    """Create a stable signature for the terminal failure, excluding retry noise.

    This prevents repeated model calls for the same persistent failure while still allowing
    one later model call if a repair exposes a genuinely different operational defect.
    """
    cleaned = redact_secrets(log_text)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    terminal = lines[-40:]
    normalized: list[str] = []
    for line in terminal:
        if "LANE2_TRANSIENT_RETRY" in line or "LANE2_SELF_HEAL_MODEL_TRANSPORT_RETRY" in line:
            continue
        line = re.sub(
            r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+(?:Z|[+-]\d{2}:?\d{2})?\b",
            "<TIMESTAMP>",
            line,
        )
        line = re.sub(r"\battempt=\d+/\d+\b", "attempt=<N>", line)
        line = re.sub(r"\bdelay_seconds=\d+(?:\.\d+)?\b", "delay_seconds=<N>", line)
        normalized.append(line)
    signature_text = "\n".join(normalized[-20:]) or "EMPTY_FAILURE_LOG"
    return hashlib.sha256(signature_text.encode("utf-8")).hexdigest()


def _cache_path(repo_root: Path) -> Path:
    git_dir = repo_root / ".git"
    base = git_dir if git_dir.is_dir() else repo_root
    return base / "a1clean-lane2-self-heal-call-cache.json"


def _load_call_cache(repo_root: Path) -> dict[str, Any]:
    path = _cache_path(repo_root)
    if not path.is_file():
        return {
            "schema": SELF_HEAL_CACHE_SCHEMA,
            "model_calls": 0,
            "fingerprints": {},
        }
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schema": SELF_HEAL_CACHE_SCHEMA,
            "model_calls": 0,
            "fingerprints": {},
        }
    if not isinstance(obj, dict) or obj.get("schema") != SELF_HEAL_CACHE_SCHEMA:
        return {
            "schema": SELF_HEAL_CACHE_SCHEMA,
            "model_calls": 0,
            "fingerprints": {},
        }
    if not isinstance(obj.get("fingerprints"), dict):
        obj["fingerprints"] = {}
    try:
        obj["model_calls"] = max(0, int(obj.get("model_calls") or 0))
    except (TypeError, ValueError):
        obj["model_calls"] = 0
    return obj


def _save_call_cache(repo_root: Path, cache: dict[str, Any]) -> None:
    path = _cache_path(repo_root)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _response_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                chunks.append(str(part.get("text") or ""))
    return "".join(chunks).strip()


def _source_context(repo_root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in ALLOWED_REPAIR_PATHS:
        path = repo_root / rel
        if path.is_file():
            out[rel] = path.read_text(encoding="utf-8")
    return out


def _model_retry_delay(attempt: int) -> float:
    return float(min(15, 2 ** max(0, attempt - 1)))


def _call_repair_model(*, log_text: str, sources: dict[str, str]) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY_MISSING")
    model = os.environ.get("A1_L2_SELF_HEAL_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["PATCH", "RETRY_ONLY", "HARD_HOLD"]},
            "summary": {"type": "string"},
            "files": {
                "type": "array",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "enum": list(ALLOWED_REPAIR_PATHS)},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "required": ["action", "summary", "files"],
    }
    developer = (
        "You are the A1 CLEAN Lane 2 operational repair agent. Repair ONLY operational/plumbing code. "
        "Never change analytical methodology, Ruptures/STUMPY/DTW behavior, discovery plan parameters, "
        "source identity, date chronology, PASS/freeze gates, RAW content, formula/trading logic, or authority. "
        "Use PATCH only when the root cause is confidently repairable inside the allowed files. "
        "Use RETRY_ONLY for likely transient infrastructure failures. Use HARD_HOLD if a safe repair would "
        "require crossing any governance boundary. Return complete replacement content only for files changed."
    )
    user_payload = {
        "failure_log_tail": redact_secrets(log_text[-24000:]),
        "allowed_files": sources,
        "governance_invariants": {
            "next_date_from_manifest_only": True,
            "advance_only_after_verified_full_pass": True,
            "resume_from_persisted_checkpoint": True,
            "no_main_mutation": True,
            "no_raw_mutation": True,
            "no_analytical_method_change": True,
        },
    }
    body = {
        "model": model,
        "store": False,
        "reasoning": {"effort": "medium"},
        "input": [
            {"role": "developer", "content": developer},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "lane2_repair_decision",
                "strict": True,
                "schema": schema,
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    payload: dict[str, Any] | None = None
    last_error: BaseException | None = None
    for attempt in range(1, MODEL_TRANSPORT_MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            last_error = RuntimeError(f"OPENAI_REPAIR_HTTP_{exc.code}:{detail}")
            retryable = exc.code in MODEL_RETRYABLE_HTTP
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = RuntimeError(f"OPENAI_REPAIR_TRANSPORT:{type(exc).__name__}:{exc}")
            retryable = True
        if not retryable or attempt >= MODEL_TRANSPORT_MAX_ATTEMPTS:
            assert last_error is not None
            raise last_error
        delay = _model_retry_delay(attempt)
        print(
            "LANE2_SELF_HEAL_MODEL_TRANSPORT_RETRY "
            f"attempt={attempt}/{MODEL_TRANSPORT_MAX_ATTEMPTS} delay_seconds={delay:g}"
        )
        time.sleep(delay)

    if payload is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("OPENAI_REPAIR_NO_RESPONSE")
    text = _response_text(payload)
    if not text:
        raise RuntimeError("OPENAI_REPAIR_EMPTY_OUTPUT")
    result = json.loads(text)
    if not isinstance(result, dict):
        raise RuntimeError("OPENAI_REPAIR_OUTPUT_NOT_OBJECT")
    return result


def decide_repair(repo_root: Path, log_text: str) -> dict[str, Any]:
    local_hold = hard_hold_reason(log_text)
    if local_hold:
        return {"action": "HARD_HOLD", "summary": local_hold, "files": []}

    fingerprint = failure_fingerprint(log_text)
    cache = _load_call_cache(repo_root)
    prior = cache["fingerprints"].get(fingerprint)
    if isinstance(prior, dict):
        prior_action = str(prior.get("action") or "UNKNOWN")
        return {
            "action": "HARD_HOLD",
            "summary": f"REPEATED_IDENTICAL_FAILURE_NO_SECOND_MODEL_CALL:{prior_action}:{fingerprint[:16]}",
            "files": [],
        }

    if int(cache.get("model_calls") or 0) >= MAX_MODEL_CALLS_PER_WORKFLOW:
        return {
            "action": "HARD_HOLD",
            "summary": f"SELF_HEAL_MODEL_CALL_BUDGET_EXHAUSTED:{MAX_MODEL_CALLS_PER_WORKFLOW}",
            "files": [],
        }

    # Reserve the logical model-call budget before transport begins. If the process dies after
    # submitting a request, the same failure fingerprint cannot silently spend tokens again.
    cache["model_calls"] = int(cache.get("model_calls") or 0) + 1
    cache["fingerprints"][fingerprint] = {
        "action": "MODEL_CALL_RESERVED",
        "summary": "MODEL_CALL_RESERVED_BEFORE_TRANSPORT",
    }
    _save_call_cache(repo_root, cache)

    try:
        decision = _call_repair_model(log_text=log_text, sources=_source_context(repo_root))
    except Exception as exc:
        cache["fingerprints"][fingerprint] = {
            "action": "MODEL_CALL_FAILED",
            "summary": redact_secrets(str(exc))[:1000],
        }
        _save_call_cache(repo_root, cache)
        raise

    cache["fingerprints"][fingerprint] = {
        "action": decision.get("action"),
        "summary": decision.get("summary"),
    }
    _save_call_cache(repo_root, cache)
    return decision


def _guard_replacement(*, path: str, old: str, new: str) -> None:
    if path not in ALLOWED_REPAIR_PATHS:
        raise RuntimeError(f"SELF_HEAL_PATH_NOT_ALLOWED:{path}")
    if not new.strip():
        raise RuntimeError(f"SELF_HEAL_EMPTY_REPLACEMENT:{path}")
    if len(new.encode("utf-8")) > 150_000:
        raise RuntimeError(f"SELF_HEAL_REPLACEMENT_TOO_LARGE:{path}")
    try:
        ast.parse(new, filename=path)
    except SyntaxError as exc:
        raise RuntimeError(f"SELF_HEAL_SYNTAX_INVALID:{path}:{exc}") from exc

    lower = new.lower()
    if path != "src/a1clean/pattern_discovery/auto_continue.py":
        for term in FORBIDDEN_ANALYTICAL_TERMS:
            if term in lower and term not in old.lower():
                raise RuntimeError(f"SELF_HEAL_ANALYTICAL_TERM_INTRODUCED:{path}:{term}")
    else:
        for anchor in AUTO_CONTINUE_REQUIRED_ANCHORS:
            if anchor not in new:
                raise RuntimeError(f"SELF_HEAL_AUTO_CONTINUE_INVARIANT_REMOVED:{anchor}")


def apply_repair_decision(repo_root: Path, decision: dict[str, Any]) -> int:
    action = str(decision.get("action") or "")
    files = decision.get("files") or []
    if action == "RETRY_ONLY":
        if files:
            raise RuntimeError("SELF_HEAL_RETRY_ONLY_MUST_NOT_CHANGE_FILES")
        return 10
    if action == "HARD_HOLD":
        if files:
            raise RuntimeError("SELF_HEAL_HARD_HOLD_MUST_NOT_CHANGE_FILES")
        return 20
    if action != "PATCH":
        raise RuntimeError(f"SELF_HEAL_ACTION_INVALID:{action}")
    if not isinstance(files, list) or not files or len(files) > 2:
        raise RuntimeError("SELF_HEAL_PATCH_FILE_COUNT_INVALID")

    seen: set[str] = set()
    staged: list[tuple[Path, str]] = []
    for item in files:
        if not isinstance(item, dict):
            raise RuntimeError("SELF_HEAL_PATCH_ITEM_INVALID")
        rel = str(item.get("path") or "")
        new = str(item.get("content") or "")
        if rel in seen:
            raise RuntimeError(f"SELF_HEAL_DUPLICATE_PATH:{rel}")
        seen.add(rel)
        target = (repo_root / rel).resolve()
        try:
            target.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise RuntimeError(f"SELF_HEAL_PATH_ESCAPE:{rel}") from exc
        old = target.read_text(encoding="utf-8") if target.is_file() else ""
        _guard_replacement(path=rel, old=old, new=new)
        staged.append((target, new))

    for target, new in staged:
        target.write_text(new, encoding="utf-8", newline="\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lane2-self-heal")
    parser.add_argument("--failure-log", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path.cwd(), type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    log_text = args.failure_log.read_text(encoding="utf-8", errors="replace")
    decision = decide_repair(repo_root, log_text)

    exit_code = apply_repair_decision(repo_root, decision)
    args.result.write_text(
        json.dumps(
            {
                "schema": "A1_LANE2_GOVERNED_SELF_HEAL_RESULT_V1",
                "action": decision.get("action"),
                "summary": decision.get("summary"),
                "changed_files": [item.get("path") for item in decision.get("files", [])],
                "exit_code": exit_code,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"LANE2_SELF_HEAL action={decision.get('action')} summary={decision.get('summary')}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
