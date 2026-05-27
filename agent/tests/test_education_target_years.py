"""Education target year logic — mirrors lib/educationTargetYear.ts."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from io import StringIO
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Financial_Planning.education_target_years import (
    COURSE_DURATION,
    DEFAULT_UG_DURATION,
    compute_education_target_years,
    normalize_course,
    parse_duration,
    resolve_duration,
    ug_start_year_from_dob,
)
from Financial_Planning.Nodes.child_education_nodes import calculate_education_funding
from Financial_Planning.Utilities.utility_functions import calculate_future_value

CHILD_DOB = "2010-06-01"
DOB_DATE = date(2010, 6, 1)
FIXED_TODAY = date(2026, 5, 25)
UG_START = 2028  # 2010 + 18


def _child(
    *,
    ug_stream="B.Tech",
    pg_stream="MBA",
    pg_dest="Domestic",
    course_duration_ug=None,
    course_duration_pg=None,
):
    row = {
        "name_of_kid": "TestKid",
        "graduation_stream": ug_stream,
        "graduation_destination": "Domestic",
        "current_fees_of_graduation": 1_000_000,
        "post_graduation_stream": pg_stream,
        "post_graduation_destination": pg_dest,
        "current_fees_of_post_graduation": 1_200_000,
        "scheme_for_education": [],
    }
    if course_duration_ug is not None:
        row["course_duration_ug"] = course_duration_ug
    if course_duration_pg is not None:
        row["course_duration_pg"] = course_duration_pg
    return row


class TestNormalizeCourse:
    def test_btech_variants(self):
        assert normalize_course("B.Tech") == "BTECH"
        assert normalize_course("b tech") == "BTECH"
        assert normalize_course("BTECH") == "BTECH"

    def test_mtech_variants(self):
        assert normalize_course("M.Tech") == "MTECH"


class TestParseDuration:
    def test_none_defaults_to_four(self):
        assert parse_duration(None) == DEFAULT_UG_DURATION

    def test_integer(self):
        assert parse_duration(5) == 5

    def test_string_with_digits(self):
        assert parse_duration("5 years") == 5

    def test_empty_string_defaults(self):
        assert parse_duration("") == DEFAULT_UG_DURATION


class TestResolveDuration:
    def test_known_ug_streams(self):
        assert resolve_duration("MBBS", None) == 5
        assert resolve_duration("B.Tech", None) == 4
        assert resolve_duration("BCom", None) == 3
        assert resolve_duration("BBA", None) == 3

    def test_known_pg_streams(self):
        assert resolve_duration("MD", None) == 3
        assert resolve_duration("MBA", None) == 2
        assert resolve_duration("MTech", None) == 2

    def test_na_returns_zero(self):
        assert resolve_duration("NA", None) == 0

    def test_other_uses_airtable_field(self):
        assert resolve_duration("Other", "6") == 6
        assert resolve_duration("Other", 2) == 2

    def test_other_empty_warns_and_defaults(self, capsys):
        assert resolve_duration("Other", None) == DEFAULT_UG_DURATION
        assert "WARN Other course missing duration" in capsys.readouterr().out

    def test_unknown_warns_and_defaults(self, capsys):
        assert resolve_duration("UnknownCourse", None) == DEFAULT_UG_DURATION
        assert "WARN unknown course" in capsys.readouterr().out

    def test_known_stream_ignores_airtable_duration(self):
        assert resolve_duration("MBBS", 99) == 5


class TestComputeEducationTargetYears:
    def test_mbbs_md(self):
        t = compute_education_target_years(_child(ug_stream="MBBS", pg_stream="MD"), DOB_DATE)
        assert t["ug_start_year"] == UG_START
        assert t["ug_duration"] == 5
        assert t["ug_target_year"] == UG_START + 5
        assert t["pg_duration"] == 3
        assert t["pg_target_year"] == UG_START + 5 + 3

    def test_btech_bcom_bba(self):
        assert compute_education_target_years(_child(ug_stream="B.Tech", pg_stream="NA", pg_dest="NA"), DOB_DATE)["ug_duration"] == 4
        assert compute_education_target_years(_child(ug_stream="BCom", pg_stream="NA", pg_dest="NA"), DOB_DATE)["ug_duration"] == 3
        assert compute_education_target_years(_child(ug_stream="BBA", pg_stream="NA", pg_dest="NA"), DOB_DATE)["ug_duration"] == 3

    def test_bcom_mba(self):
        t = compute_education_target_years(_child(ug_stream="BCom", pg_stream="MBA"), DOB_DATE)
        assert t["ug_target_year"] == UG_START + 3
        assert t["pg_duration"] == 2
        assert t["pg_target_year"] == UG_START + 3 + 2

    def test_engineering_mtech(self):
        t = compute_education_target_years(_child(ug_stream="B.Tech", pg_stream="MTech"), DOB_DATE)
        assert t["ug_target_year"] == UG_START + 4
        assert t["pg_duration"] == 2
        assert t["pg_target_year"] == UG_START + 4 + 2

    def test_na_skips_pg(self):
        t = compute_education_target_years(
            _child(ug_stream="B.Tech", pg_stream="NA", pg_dest="NA"),
            DOB_DATE,
        )
        assert t["pg_target_year"] is None
        assert t["pg_duration"] == 0

    def test_ug_other_uses_course_duration_ug(self):
        t = compute_education_target_years(
            _child(ug_stream="Other", pg_stream="NA", pg_dest="NA", course_duration_ug="6"),
            DOB_DATE,
        )
        assert t["ug_duration"] == 6
        assert t["ug_target_year"] == UG_START + 6

    def test_pg_other_uses_course_duration_pg(self):
        t = compute_education_target_years(
            _child(ug_stream="B.Tech", pg_stream="Other", course_duration_pg="2"),
            DOB_DATE,
        )
        assert t["pg_duration"] == 2
        assert t["pg_target_year"] == UG_START + 4 + 2

    def test_unknown_ug_stream_defaults_to_four(self):
        t = compute_education_target_years(_child(ug_stream="Mystery", pg_stream="NA", pg_dest="NA"), DOB_DATE)
        assert t["ug_duration"] == DEFAULT_UG_DURATION


def _education_state(child_row: dict) -> dict:
    return {
        "client_data": {
            "client_data": {
                "children": [{"child_name": "TestKid", "child_dob": CHILD_DOB}],
            },
            "education_planning": [child_row],
        },
    }


@patch("Financial_Planning.Nodes.child_education_nodes.date")
def test_calculate_education_funding_graph_path_and_future_costs(mock_date_module):
    mock_date_module.today.return_value = FIXED_TODAY

    child = _child(ug_stream="MBBS", pg_stream="MD")
    result = calculate_education_funding(_education_state(child))
    cd = result["client_data"]
    goals = cd["education_planning_summary"]
    by_child = cd["education_target_years_by_child"]["TestKid"]

    assert by_child["ug_target_year"] == UG_START + 5
    assert by_child["pg_target_year"] == UG_START + 5 + 3

    ug_goals = [g for g in goals if g["type"] == "UG"]
    pg_goals = [g for g in goals if g["type"] == "PG"]
    assert len(ug_goals) == 1
    assert len(pg_goals) == 1

    ug = ug_goals[0]
    pg = pg_goals[0]
    assert ug["target_year"] == UG_START + 5
    assert pg["target_year"] == UG_START + 5 + 3
    assert ug["ug_duration"] == 5
    assert pg["pg_duration"] == 3

    expected_ug_fv = round(calculate_future_value(1_000_000, 0.06, UG_START + 5 - FIXED_TODAY.year), 2)
    expected_pg_fv = round(calculate_future_value(1_200_000, 0.06, UG_START + 5 + 3 - FIXED_TODAY.year), 2)
    assert ug["future_cost"] == expected_ug_fv
    assert pg["future_cost"] == expected_pg_fv


@patch("Financial_Planning.Nodes.child_education_nodes.date")
def test_na_excludes_pg_goal_and_cost(mock_date_module):
    mock_date_module.today.return_value = FIXED_TODAY
    child = _child(ug_stream="B.Tech", pg_stream="NA", pg_dest="NA")
    result = calculate_education_funding(_education_state(child))
    goals = result["client_data"]["education_planning_summary"]
    assert [g["type"] for g in goals] == ["UG"]
    assert result["client_data"]["education_target_years_by_child"]["TestKid"]["pg_target_year"] is None


def test_ug_start_year_from_dob_matches_fixed_eighteen_basis():
    assert ug_start_year_from_dob(DOB_DATE) == UG_START


def test_course_duration_constants():
    assert COURSE_DURATION["MBBS"] == 5
    assert COURSE_DURATION["BTECH"] == 4
