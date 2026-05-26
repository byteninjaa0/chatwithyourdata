"""Term insurance requirement in make-plan summary output."""

from financial_plan_runner import summarize_plan_state


def test_term_insurance_requirement_in_plan_summary():
    state = {
        "client_data": {
            "client_data": {"name": "Test Client"},
            "education_planning_summary": [{"future_cost": 2_000_000}],
        },
        "required_retirement_corpus": {
            "client_info": {"current_monthly_expenses": 50_000},
        },
        "liabilities": [{"outstanding_balance": 1_500_000}],
        "liquid_pool": 500_000,
        "term_insurance_summary": {
            "pv_of_expenses": 10_000_000,
            "kids_education_cost": 2_000_000,
            "current_liabilities": 1_500_000,
            "existing_cover": 5_000_000,
            "liquidable_assets": 500_000,
            "total_term_required": 8_000_000,
        },
        "financial_overview": {},
        "optimal_goal_allocation": {},
    }

    summary = summarize_plan_state(state)
    assert "term_insurance_requirement" in summary

    ti = summary["term_insurance_requirement"]
    assert ti is not None
    assert ti["total_cover_required"] == 8_000_000
    assert ti["breakdown"]["income_replacement_corpus"] == 10_000_000
    assert ti["breakdown"]["kids_education_cost"] == 2_000_000
    assert ti["breakdown"]["outstanding_liabilities"] == 1_500_000
    assert ti["breakdown"]["less_existing_cover"] == -5_000_000
    assert ti["breakdown"]["less_liquid_assets"] == -500_000
