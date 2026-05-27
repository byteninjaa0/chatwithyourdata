"""
Shared education target-year logic (UG fixed start at 18, PG immediately after UG).
Used by calculate_education_funding and mirrored in lib/educationTargetYear.ts.
"""

from __future__ import annotations

from datetime import date
from typing import Any

UG_START_AGE = 18
DEFAULT_UG_DURATION = 4

# Normalized course key -> years (UG + PG). Edit durations here only.
COURSE_DURATION: dict[str, int] = {
    "BTECH": 4,
    "MBBS": 5,
    "BCOM": 3,
    "BBA": 3,
    "MTECH": 2,
    "MBA": 2,
    "MD": 3,
}


def normalize_course(value: Any) -> str:
    """Case-insensitive; strips non-alphanumeric ('B.Tech' -> 'BTECH')."""
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def parse_duration(value: Any, default: int = DEFAULT_UG_DURATION) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else default


def _is_empty_duration(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def resolve_duration(
    course_value: Any,
    airtable_other_duration: Any,
    default: int = DEFAULT_UG_DURATION,
) -> int:
    """Known stream -> hardcoded years; 'Other' -> Airtable duration field; NA -> 0."""
    key = normalize_course(course_value)
    if key == "NA":
        return 0
    if key in COURSE_DURATION:
        return COURSE_DURATION[key]
    if key == "OTHER":
        if _is_empty_duration(airtable_other_duration):
            print(f"[edu] WARN Other course missing duration, using default {default}")
            return default
        parsed = parse_duration(airtable_other_duration, default)
        if parsed == default and _is_empty_duration(airtable_other_duration):
            print(f"[edu] WARN Other course missing duration, using default {default}")
        return parsed
    print(f"[edu] WARN unknown course '{course_value}', using default {default}")
    return default


def ug_start_year_from_dob(dob: date, start_age: int = UG_START_AGE) -> int:
    """Year the child turns `start_age` (existing backend basis: dob.year + 18)."""
    return dob.year + start_age


def _ug_other_duration(child: dict[str, Any]) -> Any:
    return child.get("course_duration_ug", child.get("course_duration"))


def _pg_other_duration(child: dict[str, Any]) -> Any:
    return child.get("course_duration_pg", child.get("post_graduation_course_duration"))


def compute_education_target_years(
    child: dict[str, Any],
    dob: date,
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Compute UG/PG target years for one child education_plan record."""
    _ = reference_date  # reserved; ug start uses dob.year + 18 only

    ug_start_year = ug_start_year_from_dob(dob)
    ug_stream = child.get("graduation_stream")
    ug_duration = resolve_duration(ug_stream, _ug_other_duration(child), DEFAULT_UG_DURATION)
    ug_target_year = ug_start_year + ug_duration

    pg_stream_raw = child.get("post_graduation_stream")
    pg_duration = resolve_duration(pg_stream_raw, _pg_other_duration(child), DEFAULT_UG_DURATION)

    pg_target_year: int | None = None
    if pg_duration > 0 and normalize_course(pg_stream_raw) != "NA":
        dest = str(child.get("post_graduation_destination") or "").strip().upper()
        if dest not in ("", "NA", "NONE"):
            pg_target_year = ug_target_year + pg_duration

    return {
        "ug_duration": ug_duration,
        "ug_start_year": ug_start_year,
        "ug_target_year": ug_target_year,
        "pg_stream": pg_stream_raw,
        "pg_duration": pg_duration if pg_target_year is not None else 0,
        "pg_target_year": pg_target_year,
    }


# Backward-compatible aliases used by older tests/imports
normalize_pg_stream_key = normalize_course


def pg_duration_from_stream(
    stream: Any,
    *,
    ug_style_duration: int,
    default_other: int = DEFAULT_UG_DURATION,
) -> int:
    return resolve_duration(stream, ug_style_duration, default_other)
