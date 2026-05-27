"""
Child Education Planning - Cost Estimation & Funding

What this file does:
This script manages children's education planning including cost estimation, college selection,
and funding gap analysis for both undergraduate and postgraduate education.

What this file contains and processes:
- education_fees_calculation: Estimates education costs by scraping/calculating average fees for top colleges based on stream (Medical/Engineering/Commerce/General) and destination (Domestic/International)
- calculate_education_funding: Analyzes education funding by computing future costs, allocated funds, scheme values, surplus utilization, and final gaps for each child's UG/PG goals chronologically
"""

from Financial_Planning.Models.client_data_state import ClientState
from datetime import datetime, date
from Financial_Planning.Utilities.utility_functions import (calculate_future_value, calculate_sip_future_value, calculate_required_sip)
import pickle
from pathlib import Path

from Financial_Planning.education_fee_defaults import (
    DEFAULT_GRADUATION_FEES,
    DEFAULT_POST_GRADUATION_FEES,
)
from Financial_Planning.education_target_years import compute_education_target_years


def _fee_scrapper_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "College_Fees_Scrapper"


def _load_graduation_fees():
    p = _fee_scrapper_dir() / "default_graduation_fees.pkl"
    if p.exists():
        with open(p, "rb") as f:
            return pickle.load(f)
    return list(DEFAULT_GRADUATION_FEES)


def _load_post_graduation_fees():
    p = _fee_scrapper_dir() / "default_post_graduation_fees.pkl"
    if p.exists():
        with open(p, "rb") as f:
            return pickle.load(f)
    return list(DEFAULT_POST_GRADUATION_FEES)

def education_fees_calculation(state: ClientState): 
    """
    Estimate education costs for each child in the client’s plan.
    For every child, the function:
      - Confirms education destination (domestic/international).
      - Scrapes/estimates tuition fees for the chosen stream.
      - Calculates average costs across top colleges.
      - Updates the plan with college list and fee estimates.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: education_fees_calculation \n")
    print("Fetches the current education cost based on stream and location... \n")
    kids_education=state['client_data']['education_planning']

    for education_plan in kids_education: 

        if education_plan['graduation_destination'] is None:
            education_plan['graduation_destination']='Domestic'
            # print(f"Default undergraduation for {education_plan['name_of_kid']} is choosen as Domestic, as graduation destination is not choosen")
        
        # if education_plan['graduation_destination']=='International' and (1+state['retirement_goal'][0]['corpus_needed'])*100/(state['required_retirement_corpus']['recommendation']['recommended_corpus']) > 20 :
        #     education_plan['graduation_destination']='Domestic' 
        #     print(f"under-graduation destination for {education_plan['name_of_kid']} is deprioritized to Domestic as retirement corpus gap is more than 20% percent.")
        
        if education_plan['graduation_stream'] is None: 
            education_plan['graduation_stream'] = 'B.Tech'
            # print("default graduation for stream {education_plan['name_of_kid']} is Engineering, as no stream was selected")
        
        if education_plan['graduation_destination']=='Domestic' or education_plan['graduation_destination']=='International':
            edu_type='undergraduation' 

            graduation_details = _load_graduation_fees()
            
            for grad_info in graduation_details: 
                if grad_info['graduation_destination']==education_plan['graduation_destination'] and grad_info['graduation_stream']==education_plan['graduation_stream']:
                    education_plan['current_fees_of_graduation']=grad_info['current_fees_of_graduation']
            if "current_fees_of_graduation" not in education_plan:
                education_plan["current_fees_of_graduation"] = 1_000_000
        if education_plan['post_graduation_destination']=='Domestic' or education_plan['post_graduation_destination']=='International': 

            # if education_plan['post_graduation_destination']=='International' and (1+state['retirement_goal'][0]['corpus_needed'])*100/(state['required_retirement_corpus']['recommendation']['recommended_corpus']) > 20 :
            #     education_plan['post_graduation_destination']='Domestic' 
            #     print(f"post-graduation destination for {education_plan['name_of_kid']} is deprioritized to Domestic as retirement corpus gap is more than 20% percent.") 

            if education_plan['post_graduation_destination'] == None:
                education_plan['post_graduation_destination']='Domestic'
                # print(f"Default post-undergraduation destination for {education_plan['name_of_kid']} is considered as Domestic, as post-graduation destination is not choosen")
            
            if education_plan['post_graduation_stream'] == None:
                education_plan['post_graduation_stream'] = 'MBA'
                # print(f"default post-graduation stream for {education_plan['name_of_kid']} is MBA, as no particluar stream was selected")

            edu_type='postgraduation'

            ####################################### import pickle
            
            post_graduation_details = _load_post_graduation_fees()
            
            for grad_info in post_graduation_details: 
                if grad_info['post_graduation_destination']==education_plan['post_graduation_destination'] and grad_info['post_graduation_stream']==education_plan['post_graduation_stream']:
                    education_plan['current_fees_of_post_graduation']=grad_info['current_fees_of_post_graduation']
            if "current_fees_of_post_graduation" not in education_plan:
                education_plan["current_fees_of_post_graduation"] = 1_200_000
    print(f"education_plan: {education_plan}\n")
    print("--------------------------"*6)
    return state

def calculate_education_funding(state: ClientState):
    """
    Analyzes and calculates the funding for the client's children's education goals.

    This function processes each child's undergraduate (UG) and postgraduate (PG)
    education goals, calculates future costs and the future value of existing
    investments, and determines any funding gaps or surpluses. Surpluses from
    earlier goals are utilized for later ones. Crucially, it tracks used investment
    schemes to ensure they are not double-counted for multiple goals. Finally, it
    computes the required monthly SIP to bridge any remaining gaps.

    Args:
        client_data (dict): A dictionary containing the client's financial and personal data.

    Returns:
        dict: A dictionary containing the original client data updated with a detailed
              education planning summary. The summary includes the future cost of
              each goal, the value of allocated funds, any gaps or surpluses,
              and the required monthly investment to meet the goals.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_education_funding \n")
    print("[calculate_education_funding] UG start age=18; durations from stream mapping + Other Airtable fields\n")
    print("Calculating the future value of the education fees and defines education goal for each child... \n")
    client_data=state['client_data']
    
    today = date.today()
    education_goals = []
    education_target_years_by_child: dict = {}
    
    # 1. Consolidate all education goals into a single list
    for child in client_data['education_planning']:
        child_dob = None
        for c in client_data['client_data']['children']:             
            if c['child_name'] == child['name_of_kid']:              # maybe this will have to be converted into similarity check.
                child_dob = datetime.strptime(c['child_dob'], '%Y-%m-%d').date()
                break
        
        if not child_dob:
            continue

        targets = compute_education_target_years(child, child_dob, reference_date=today)
        education_target_years_by_child[child['name_of_kid']] = targets

        ug_target_year = targets['ug_target_year']
        ug_years_to_goal = ug_target_year - today.year
        print(f'child: {child}, targets: {targets}')
        education_goals.append({
            "name": child['name_of_kid'],
            "type": 'UG',
            "stream": child['graduation_stream'],
            "destination": child['graduation_destination'],
            "target_year": ug_target_year,
            "years_to_goal": ug_years_to_goal,
            "current_cost": child['current_fees_of_graduation'],
            "allocated_funds": child.get('fund_allocated_for_graduation', 0),
            "schemes": child.get('scheme_for_education', []),
            'funded_from': [],
            "ug_duration": targets['ug_duration'],
            "ug_start_year": targets['ug_start_year'],
            "pg_stream": targets.get('pg_stream'),
            "pg_duration": targets.get('pg_duration'),
            "pg_target_year": targets.get('pg_target_year'),
        })

        pg_target_year = targets.get('pg_target_year')
        if pg_target_year is not None and targets.get('pg_duration', 0) > 0:
            pg_years_to_goal = pg_target_year - today.year
            education_goals.append({
                "name": child['name_of_kid'],
                "type": "PG",
                "stream": child.get("post_graduation_stream"),
                "destination": child.get('post_graduation_destination'),
                "target_year": pg_target_year,
                "years_to_goal": pg_years_to_goal,
                "current_cost": child['current_fees_of_post_graduation'],
                "allocated_funds": child.get('fund_allocated_for_post_graduation', 0),
                "schemes": child.get('scheme_for_education', []),
                'funded_from': [],
                "ug_duration": targets['ug_duration'],
                "ug_start_year": targets['ug_start_year'],
                "pg_stream": targets.get('pg_stream'),
                "pg_duration": targets.get('pg_duration'),
                "pg_target_year": pg_target_year,
            })
        
    # 2. Sort goals chronologically by target year
    education_goals.sort(key=lambda x: x['target_year'])
    
    surplus_pool = 0.0
    # NEW: Initialize a set to track schemes that have been allocated to a goal.
    used_schemes = set()
    
    # 3. Process each goal in chronological order
    for goal in education_goals:
        # Calculate future cost of education (assuming 6% inflation)
        #goal['current_cost']
        future_cost = calculate_future_value(goal['current_cost'], 0.06, goal['years_to_goal'])
        goal['future_cost'] = round(future_cost, 2)
        
        total_future_corpus = 0.0
        
        # Calculate FV of funds already allocated (assuming 9% growth)
        if goal['allocated_funds']>0: 
            fv_allocated = calculate_future_value(goal['allocated_funds'], 0.09, goal['years_to_goal'])
            total_future_corpus += fv_allocated
            goal['fv_of_allocated_funds'] = round(fv_allocated, 2)
            goal['funded_from'].append({'fv_of_allocated_funds': round(fv_allocated, 2)})
        else: 
            goal['fv_of_allocated_funds'] = 0.0

        schemes_list=[]
        # Calculate FV of dedicated education schemes
        goal['fv_of_schemes'] = 0.0
        for scheme in goal['schemes']:
            # NEW: Check if the scheme has already been used for a prior goal.
            if scheme['scheme_name'] in used_schemes:
                continue # Skip this scheme as it's already allocated.

            scheme_end_date = datetime.strptime(scheme['end_date'], '%Y-%m-%d').date()
            # Only use scheme if it matures on or before the goal's target year
            if scheme_end_date.year <= goal['target_year']:
                years_in_scheme = (scheme_end_date - datetime.strptime(scheme['start_date'], '%Y-%m-%d').date()).days / 365.25
                fv_scheme = calculate_sip_future_value(scheme['monthly_investment'], scheme['interest_rate'], years_in_scheme)
                
                # If scheme matures before goal, grow the lump sum until the goal year
                years_post_maturity = goal['target_year'] - scheme_end_date.year
                if years_post_maturity > 0:
                    fv_scheme = calculate_future_value(fv_scheme, 0.09, years_post_maturity)
                
                total_future_corpus += fv_scheme
                goal['fv_of_schemes'] += round(fv_scheme, 2)
                schemes_list.append(scheme['scheme_name'])
                # NEW: Mark this scheme as used so it's not double-counted.
                used_schemes.add(scheme['scheme_name'])
    
        if goal['fv_of_schemes']>0:
            s_lists=', '.join(schemes_list)
            goal['funded_from'].append({s_lists:goal['fv_of_schemes'] })
        
        goal['total_future_corpus'] = round(total_future_corpus, 2)
        
        # Determine the initial funding gap
        initial_gap = future_cost - total_future_corpus
        
        # Utilize surplus from previous goals 
        if initial_gap > 0.1*future_cost and surplus_pool > 0:    # if 90% of goal is covered then no allocation 
            used_surplus = min(initial_gap, surplus_pool)
            # print(f"used surplus: {used_surplus}")
            # print(goal['funded_from']) 
            initial_gap -= used_surplus
            surplus_pool -= used_surplus 
            goal['surplus_utilized'] = round(used_surplus, 2)
            goal['funded_from'].append({'surplus_from_previous_edu_investments': used_surplus})  
        else: 
            goal['surplus_utilized'] = 0.0 
            
        # Final calculation for gap or surplus 
        if initial_gap > 0.1*future_cost:                         # if 90% of goal is covered then no allocation
            goal['final_gap'] = round(initial_gap, 2) 
            goal['surplus_generated'] = 0.0 
            #Calculate required monthly SIP to cover the remaining gap (assuming 12% return)
            #required_sip = calculate_required_sip(initial_gap, 0.12, goal['years_to_goal'])
            #goal['required_monthly_investment'] = round(required_sip, 2)
        elif initial_gap<0:
            goal['final_gap'] = 0.0
            # Add the surplus to the pool for next goals
            surplus = -initial_gap 
            surplus_pool += surplus
            goal['surplus_generated'] = round(surplus, 2)
            #goal['required_monthly_investment'] = 0.0

        else: 
            goal['final_gap'] = 0.0
            # Add the surplus to the pool for next goals
            surplus = 0 
            surplus_pool += surplus
            goal['surplus_generated'] = round(surplus, 2)
    
    # 4. Attach the detailed plan to the original client data for a complete report
    client_data['education_planning_summary'] = education_goals
    client_data['education_target_years_by_child'] = education_target_years_by_child

    education_planning=[]
    for goal in education_goals:
        education_planning.append({'goal_name': goal['name'] + " " + goal['type'], 'stream': goal['stream'], 'destination': goal['destination'], 'target_corpus': goal['future_cost'], 'corpus_needed': goal['final_gap'], 'corpus_gap': goal['final_gap'], 'target_year': goal['target_year'], 'funded_from': goal['funded_from'] }) 
    print(f"education_planning : {education_planning}\n")
    print("--------------------------"*6)
    return {'client_data': client_data, 'children_education_planning': education_planning}