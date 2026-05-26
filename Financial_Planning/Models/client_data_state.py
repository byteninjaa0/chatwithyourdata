"""
State Schema Definitions - Workflow Data Models

What this file does:
This script defines TypedDict schemas that represent the state structure for LangGraph workflows.
It ensures type safety and clarity for data flowing through the financial planning pipeline.

What this file contains:
- ClientState: Main state schema for financial planning workflow with fields for:
  - client_data, risk_appetite, retirement data, goals, assets, allocations, and surplus tracking
- AgentState: State schema for agentic workflows with message history
"""

from typing import Annotated, List, TypedDict, Literal
import json
from operator import add
from langchain_core.messages import AnyMessage

class ClientState(TypedDict):

    client_data: json                         # input
    risk_appetite : dict 
    children_education_planning: dict 
    required_retirement_corpus: json       
    retirement_schemes_fv: json
    goals: list 
    retirement_assets: list 
    liquid_assets : list
    fixed_assets : list 
    liquid_pool : float  
    fixed_asset_pool : float 
    goal_funding : Annotated[list[dict], add]
    asset_percentages : dict
    financial_overview : dict
    sorted_goals: dict
    surplus_from_goals : float
    financial_goals : list 
    liability_allocation: Annotated[list[dict], add]
    used_monthly_surplus : Annotated[list[float], add]            #float
    used_liquid_surplus : Annotated[list[float], add]  #float 
    EMI_allocated : bool 
    freed_timeline : Annotated[list[dict], add]   #dict 
    EMI_allocation: bool 
    loan_prepayed_times : int
    liabilities : list 
    unused_monthly_surplus : Annotated[List[float], add] 
    extra_monthly_surplus_investment_plan : dict
    optimal_goal_allocation : dict
    optimal_loan_allocation : dict
    final_unused_monthly_surplus : float 
    monthly_surplus : float
    retirement_goal : list
    optimal_selected : bool 
    at_optimal: bool
    loans_exist : bool
    loan_prepayment_analysis : str
    sip_for_goal : list
    emergency_fund_status : dict
    ulip_opportunity_cost_data : dict
    term_insurance_summary : dict

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add]
