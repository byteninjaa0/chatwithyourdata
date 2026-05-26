"""
Financial Planning Workflow - Main Orchestrator

What this file does:
This script defines and executes the complete financial planning workflow using LangGraph.
It orchestrates the entire analysis pipeline from client data input to final resource allocation.

What this file contains and processes:
- graph: StateGraph instance configured with ClientState
- calculate_age: Computes ages of all family members from birth dates
- goals_future_value: Calculates future values and gaps for financial goals
- calculate_education_funding: Analyzes education costs and funding requirements
- calculate_retirement_corpus: Computes required retirement corpus using multiple methods
- calculate_all_retirement_investments: Projects future values of retirement schemes
- retirement_goal: Evaluates retirement corpus gap and creates retirement goal
- asset_basket_classification: Categorizes investments into liquid/fixed/retirement baskets
- calculate_total_asset_value: Sums up total liquid asset pool
- calculate_fixed_assets_value: Calculates total fixed asset pool
- check_and_allocate_emergency_fund: Ensures client has adequate emergency fund (6x monthly expenses), allocates from liquid assets if needed
- plan_goals: Allocates resources to fund goals using greedy allocation strategy
- calculate_asset_percentages_and_ratios: Computes asset allocation ratios and financial health metrics
- risk_appetite_assessment: LLM-powered analysis of client's risk tolerance
- goal_prioritization: LLM-assisted goal ranking by importance and urgency
- education_fees_calculation: Estimates education costs based on stream and destination
- plan_prepayments: Strategizes loan prepayment allocation
- freed_emi_by_year: Tracks EMI amounts freed when loans close naturally
- invest_monthly_surplus: Allocates leftover surplus into debt/hybrid/equity funds
- choose_optimal_strategy: Selects best allocation strategy across multiple scenarios
- add_goals: Consolidates all goals (retirement, education, financial) into unified list
- workflow: Compiled graph ready for execution
- final_state: Executed workflow result with complete financial plan
"""

from langgraph.graph import StateGraph, START, END
from Financial_Planning.Models.client_data_state import ClientState
from Financial_Planning.Nodes.basic_calculations_nodes import (calculate_age,asset_basket_classification, calculate_liquid_asset_value, calculate_fixed_assets_value, 
                                                              calculate_asset_percentages_and_ratios, invest_monthly_surplus, freed_emi_by_year, check_for_kid, check_for_pre_payment,
                                                              update_ulip_current_values, calculate_term_insurance_requirement)
from Financial_Planning.Nodes.goal_consolidation_nodes import (goals_future_value, add_goals)
from Financial_Planning.Nodes.child_education_nodes import (calculate_education_funding, education_fees_calculation)
from Financial_Planning.Nodes.retirement_nodes import (calculate_retirement_corpus, calculate_all_retirement_investments, retirement_goal)
from Financial_Planning.Nodes.allocations_nodes import (plan_goals, plan_prepayments, choose_optimal_strategy)
from Financial_Planning.Nodes.agentic_nodes import (risk_appetite_assessment, goal_prioritization)

# define graph (no side effects at import — invoke via run_financial_plan_workflow)
graph = StateGraph(ClientState)

# add nodes to graph
graph.add_node('calculate_age', calculate_age)    
graph.add_node('goals_future_value', goals_future_value)
graph.add_node('calculate_education_funding', calculate_education_funding)
graph.add_node('calculate_retirement_corpus', calculate_retirement_corpus)
graph.add_node('calculate_all_retirement_investments', calculate_all_retirement_investments)
graph.add_node('retirement_goal', retirement_goal)
graph.add_node('asset_basket_classification', asset_basket_classification)
graph.add_node('calculate_liquid_asset_value', calculate_liquid_asset_value)
graph.add_node('calculate_term_insurance_requirement', calculate_term_insurance_requirement)
graph.add_node('calculate_fixed_assets_value', calculate_fixed_assets_value)
#graph.add_node('check_and_allocate_emergency_fund', check_and_allocate_emergency_fund)
graph.add_node('plan_goals', plan_goals)
graph.add_node('calculate_asset_percentages_and_ratios', calculate_asset_percentages_and_ratios)
graph.add_node('risk_appetite_assessment', risk_appetite_assessment)
graph.add_node('goal_prioritization', goal_prioritization)
graph.add_node('education_fees_calculation',education_fees_calculation)
graph.add_node('plan_prepayments', plan_prepayments)
graph.add_node('freed_emi_by_year',freed_emi_by_year)
graph.add_node('invest_monthly_surplus', invest_monthly_surplus)
graph.add_node('choose_optimal_strategy', choose_optimal_strategy)
graph.add_node('add_goals', add_goals)
graph.add_node('update_ulip_current_values', update_ulip_current_values)

# create graph edges
graph.add_edge(START, 'calculate_age') 
graph.add_edge('calculate_age','calculate_retirement_corpus')
graph.add_edge('calculate_retirement_corpus', 'calculate_all_retirement_investments')
graph.add_edge('calculate_all_retirement_investments', 'retirement_goal') 
graph.add_conditional_edges('retirement_goal', check_for_kid, {True: 'education_fees_calculation', False: 'goals_future_value' })
graph.add_edge('education_fees_calculation', 'calculate_education_funding')
graph.add_edge('calculate_education_funding', 'goals_future_value' )
graph.add_edge('goals_future_value', 'add_goals')    
graph.add_edge('add_goals', 'update_ulip_current_values')
graph.add_edge('update_ulip_current_values','asset_basket_classification')  
graph.add_edge('asset_basket_classification', 'risk_appetite_assessment') 
graph.add_edge('risk_appetite_assessment', 'calculate_liquid_asset_value')
graph.add_edge('calculate_liquid_asset_value', 'calculate_term_insurance_requirement')
graph.add_edge('calculate_term_insurance_requirement', 'calculate_fixed_assets_value')
graph.add_edge('calculate_fixed_assets_value','calculate_asset_percentages_and_ratios')
graph.add_edge('calculate_asset_percentages_and_ratios', 'goal_prioritization')
graph.add_edge('goal_prioritization','freed_emi_by_year')
graph.add_edge('freed_emi_by_year' ,'plan_goals') 
graph.add_conditional_edges('plan_goals', check_for_pre_payment, {True: 'plan_prepayments', False : 'choose_optimal_strategy' , 'END': END}) # condition to be added here as well
graph.add_edge('choose_optimal_strategy', 'invest_monthly_surplus') 
graph.add_edge('plan_prepayments', 'plan_goals')   
graph.add_edge('invest_monthly_surplus', END) 

# Compiled graph — call from backend runner with client-specific state
workflow = graph.compile()


def run_financial_plan_workflow(client_data: dict, recursion_limit: int = 50) -> dict:
    """Run the LangGraph financial planning pipeline for one client payload."""
    initial_state = {
        "client_data": client_data,
        "EMI_allocated": False,
        "loan_prepayed_times": 0,
        "used_monthly_surplus": [0],
        "optimal_selected": False,
    }
    return workflow.invoke(initial_state, config={"recursion_limit": recursion_limit})
