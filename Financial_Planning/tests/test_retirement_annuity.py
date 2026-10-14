"""Unit tests for calculate_retirement_annuity (income-preservation, used-sources only)."""

from Financial_Planning.Nodes.retirement_nodes import calculate_retirement_annuity
from Financial_Planning.Utilities.utility_functions import calculate_future_value


def _base_state(
    *,
    desired_monthly_annuity: float = 50_000,
    surplus_monthly: float = 50_000,
    fd_fv: float = 5_000_000,
    fd_rate: str = "6.5%",
    mf_cv: float = 2_000_000,
    mf_rate: float = 0.12,
    years_to_retirement: int = 10,
    esops=None,
    rsu_portfolio=None,
    goals=None,
    extra_breakdown=None,
):
    breakdown = {
        "fixed_deposits": {"future_value": fd_fv, "rate": fd_rate},
    }
    breakdown.update(extra_breakdown or {})
    return {
        "client_data": {
            "client_data": {
                "retirement_age": 60,
                "desired_monthly_annuity": desired_monthly_annuity,
            },
            "investment_details": {
                "financial_summary": [
                    {"other_income(rental/interest/other)": surplus_monthly},
                ],
                "mutual_funds": [
                    {"current_value": mf_cv, "expected_annual_return": mf_rate},
                ],
                "esops": esops if esops is not None else [],
                "rsu": [],
            },
        },
        "required_retirement_corpus": {
            "client_info": {"years_to_retirement": years_to_retirement},
        },
        "wealth_at_retirement": {
            "retirement_year": 2036,
            "breakdown": breakdown,
        },
        "optimal_goal_allocation": {
            "goals": goals or [],
            "rsu_portfolio": rsu_portfolio or [],
        },
    }


def test_rental_only_covers_desired_single_source_capped_to_target():
    desired = 50_000.0
    result = calculate_retirement_annuity(_base_state(desired_monthly_annuity=desired))
    annuity = result["retirement_annuity"]
    assert annuity["achievable"] is True
    assert len(annuity["sources"]) == 1
    assert annuity["sources"][0]["key"] == "rental_other_income"
    assert annuity["sources"][0]["monthly_income"] == desired
    assert annuity["total_available_monthly"] == desired
    assert all(s["required"] is True for s in annuity["sources"])
    keys = {s["key"] for s in annuity["sources"]}
    assert "fixed_deposits" not in keys
    assert "mutual_funds" not in keys


def test_multi_source_last_row_capped_and_rows_sum_to_desired():
    vested = 1_000_000.0
    esop_remaining = vested * 0.60
    years = 10
    esop_rate = 0.12
    esop_fv = calculate_future_value(esop_remaining, esop_rate, years)
    esop_monthly = (esop_fv * esop_rate) / 12
    desired = esop_monthly + 20_000.0

    state = _base_state(
        desired_monthly_annuity=desired,
        surplus_monthly=100_000,
        fd_fv=0,
        mf_cv=0,
        years_to_retirement=years,
        extra_breakdown={
            "esop": {"future_value": esop_fv, "rate": f"{esop_rate * 100:.1f}%"},
        },
    )
    state["client_data"]["investment_details"]["mutual_funds"] = []

    result = calculate_retirement_annuity(state)
    annuity = result["retirement_annuity"]
    keys = [s["key"] for s in annuity["sources"]]
    assert keys == ["esop", "rental_other_income"]
    by_key = {s["key"]: s for s in annuity["sources"]}
    assert by_key["esop"]["monthly_income"] == round(esop_monthly, 2)
    assert by_key["rental_other_income"]["monthly_income"] == 20_000.0
    used_sum = sum(s["monthly_income"] for s in annuity["sources"])
    assert round(used_sum, 2) == round(desired, 2)
    assert annuity["total_available_monthly"] == round(desired, 2)


def test_shortfall_shows_all_positive_sources_at_full_income():
    desired = 300_000.0
    state = _base_state(
        desired_monthly_annuity=desired,
        surplus_monthly=0,
        extra_breakdown={
            "esop": {"future_value": 310_584.82, "rate": "12.0%"},
        },
    )
    result = calculate_retirement_annuity(state)
    annuity = result["retirement_annuity"]
    assert annuity["achievable"] is False
    assert annuity["shortfall_monthly"] > 0
    assert annuity["total_available_monthly"] < desired
    assert annuity["total_available_monthly"] == annuity["max_monthly_annuity"]
    keys = {s["key"] for s in annuity["sources"]}
    assert "esop" in keys
    assert "fixed_deposits" in keys
    assert "mutual_funds" in keys
    assert all(s["required"] is True for s in annuity["sources"])


def test_zero_desired_annuity_returns_empty():
    state = _base_state(desired_monthly_annuity=0)
    assert calculate_retirement_annuity(state) == {}


def test_epf_ppf_and_nps_buckets_yield_income():
    """EPF/PPF at 8.5% and NPS at 7% — previously ignored entirely."""
    state = _base_state(
        desired_monthly_annuity=10_000_000,  # force every source to show
        surplus_monthly=0,
        fd_fv=0,
        mf_cv=0,
        extra_breakdown={
            "epf": {"future_value": 20_000_000, "rate": "8.4%"},
            "ppf": {"future_value": 10_000_000, "rate": "7.5%"},
            "nps": {"future_value": 5_000_000, "rate": "10%"},
        },
    )
    state["client_data"]["investment_details"]["mutual_funds"] = []
    annuity = calculate_retirement_annuity(state)["retirement_annuity"]
    by_key = {s["key"]: s for s in annuity["sources"]}

    # EPF + PPF merge into one row, yielded at the post-retirement rate (8.5%),
    # NOT at the accumulation rates stored in the breakdown.
    assert by_key["epf_ppf"]["corpus_fv"] == 30_000_000
    assert by_key["epf_ppf"]["annual_income"] == round(30_000_000 * 0.085, 2)
    assert by_key["nps"]["annual_income"] == round(5_000_000 * 0.07, 2)


def test_sip_and_freed_emi_merge_into_mutual_funds_row():
    """SIP / freed-EMI / lumpsum are MF-invested and collapse into one MF row."""
    state = _base_state(
        desired_monthly_annuity=10_000_000,
        surplus_monthly=0,
        fd_fv=0,
        mf_cv=0,
        extra_breakdown={
            "sip": {"future_value": 15_784_146, "rate": "-"},
            "freed_sip": {"future_value": 10_522_894, "rate": "-"},
            "lumpsum": {"future_value": 1_000_000, "rate": "-"},
        },
    )
    state["client_data"]["investment_details"]["mutual_funds"] = []
    annuity = calculate_retirement_annuity(state)["retirement_annuity"]
    by_key = {s["key"]: s for s in annuity["sources"]}

    expected_corpus = 15_784_146 + 10_522_894 + 1_000_000
    assert by_key["mutual_funds"]["corpus_fv"] == expected_corpus
    assert by_key["mutual_funds"]["rate"] == "10.0%"
    assert by_key["mutual_funds"]["annual_income"] == round(expected_corpus * 0.10, 2)
    assert "sip" not in by_key and "freed_sip" not in by_key


def test_real_estate_capital_excluded_to_avoid_double_count():
    """Rent is already counted; the property's capital value must not yield too."""
    state = _base_state(
        desired_monthly_annuity=10_000_000,
        surplus_monthly=50_000,
        fd_fv=0,
        mf_cv=0,
        extra_breakdown={
            "real_estate": {"future_value": 29_601_381, "rate": "3.0%"},
        },
    )
    state["client_data"]["investment_details"]["mutual_funds"] = []
    annuity = calculate_retirement_annuity(state)["retirement_annuity"]
    keys = {s["key"] for s in annuity["sources"]}

    assert "real_estate" not in keys
    assert annuity["corpus_base"] == 0.0  # property capital kept out of the base
    by_key = {s["key"]: s for s in annuity["sources"]}
    assert by_key["rental_other_income"]["annual_income"] == 50_000 * 12
