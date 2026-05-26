"""
Basic Financial Calculations - Core Computation Nodes

What this file does:
This script contains fundamental calculation nodes for the financial planning workflow.
It handles age computation, asset classification, surplus calculation, and EMI tracking.

What this file contains and processes:
- calculate_age: Computes current ages of client, spouse, and children from DOB
- asset_basket_classification: Categorizes investments into liquid/fixed/retirement baskets with unique IDs
- calculate_total_asset_value: Sums up total value of all liquid assets
- calculate_fixed_assets_value: Calculates total value of all fixed assets
- calculate_asset_percentages_and_ratios: Analyzes asset allocation, liquidity, flexibility, and spending patterns
- invest_monthly_surplus: Allocates leftover surplus into 30% debt/40% hybrid/30% equity funds
- freed_emi_by_year: Tracks monthly EMI amounts freed when loans close naturally
- check_for_kid: Conditional check if client has children
- check_for_pre_payment: Determines if loan prepayment should be triggered
"""

# basic calculations nodes: calculate age, add_goals, asset_basket_classification, calculate_total_asset_value, calculate_fixed_assets_value, calculate_asset_percentages_and_ratios, invest_monthly_surplus
from Financial_Planning.Models.client_data_state import ClientState
from Financial_Planning.Utilities.utility_functions import (fv_monthly, months_to_close, _add_months, present_loans_no_allocation, calculate_current_value)
from datetime import datetime, date

def calculate_age(state: ClientState): # calculates ages of all the individual mentioned in the client data
    """ 
    Computes the current ages of all individuals (client, spouse, and children) 
    based on their dates of birth in the provided client data.
    Purpose:
        Enhances client_data by populating the ages of all mentioned individuals 
        using the current system date.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_age \n")
    print("Calculating age and monthly surplus... \n")
    client_data=state['client_data']
    current_date = date.today()  
    if client_data['client_data']['date_of_birth']: 
        client_age=current_date.year-datetime.strptime(client_data['client_data']['date_of_birth'], '%Y-%m-%d').year
        client_data['client_data']['client_age']=client_age 
     
    if client_data['client_data']['spouse_dob']:
        spouse_age=current_date.year-datetime.strptime(client_data['client_data']['spouse_dob'], '%Y-%m-%d').year
        client_data['client_data']['spouse_age']=spouse_age 

    if client_data['client_data']['if_any_kids']==True:
        for index, child_info in enumerate(client_data['client_data']['children']):
            child_age=current_date.year-datetime.strptime(child_info['child_dob'], '%Y-%m-%d').year
            client_data['client_data']['children'][index]['child_age']=child_age
    
    monthly_surplus=(state['client_data']['investment_details']['financial_summary'][0]['monthly_salary'] + state['client_data']['investment_details']['financial_summary'][0]['other_income(rental/interest/other)']) - ( state['client_data']['investment_details']['financial_summary'][0]['monthly_expenses_excl_emis'] + 
                                                                                                                                                                                                    state['client_data']['investment_details']['financial_summary'][0]['miscellaneous_kids_education_expenses_monthly'] + 
                                                                                                                                                                                                     (state['client_data']['investment_details']['financial_summary'][0]['annual_vacation_expenses'])/12 )  
    liabilities=client_data.get('liabilities', [])
    print(f"monthly surplus: {monthly_surplus}\n")
    print("--------------------------"*6)
    return {'client_data': client_data, 'children_education_planning': [], 'financial_goals': [], 'liabilities': liabilities, 'monthly_surplus': monthly_surplus }      


def _parse_ulip_date(date_str):
    """Parse ULIP dates supporting both DD-MM-YYYY and YYYY-MM-DD."""
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue
    raise ValueError(f"Unsupported date format: {date_str}")


def back_calculate_ulip_xirr(policy, tol=1e-6, max_iter=100):
    """
    Infer ULIP XIRR from policy premium schedule and maturity value.
    """
    commencement = _parse_ulip_date(policy['commencement_date'])
    ppt, term = policy['ppt'], policy['term']
    premium, maturity = policy['premium'], policy['maturity_value']

    cashflows = []
    for yr in range(ppt):
        cashflows.append((commencement.replace(year=commencement.year + yr), -premium))
    cashflows.append((commencement.replace(year=commencement.year + term), maturity))

    base_date = cashflows[0][0]

    def npv(rate):
        return sum(cf / (1 + rate) ** ((dt - base_date).days / 365.0) for dt, cf in cashflows)

    lo, hi = -0.99, 1.5
    mid = (lo + hi) / 2
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        val = npv(mid)
        if abs(val) < tol:
            return round(mid, 6)
        lo, hi = (mid, hi) if val > 0 else (lo, mid)
    return round(mid, 6)


def calculate_ulip_opportunity_cost(policy, large_cap_rate=0.12, baf_rate=0.10, lumpsum_growth_rate=0.12):
    """Compute ULIP opportunity-cost analytics while current_value is handled separately."""
    commencement = _parse_ulip_date(policy['commencement_date'])
    today = date.today()
    annual_premium = float(policy.get('premium', 0) or 0)
    ppt = int(policy.get('ppt', 0) or 0)
    term = int(policy.get('term', 0) or 0)

    xirr = back_calculate_ulip_xirr(policy)

    years_paid = today.year - commencement.year
    if (today.month, today.day) < (commencement.month, commencement.day):
        years_paid -= 1
    years_paid = max(0, min(years_paid, ppt))

    remaining_ppt = max(0, ppt - years_paid)
    ppt_end_date = commencement.replace(year=commencement.year + ppt)
    maturity_date = commencement.replace(year=commencement.year + term)
    remaining_term = max(
        0,
        maturity_date.year - ppt_end_date.year
        - (1 if (maturity_date.month, maturity_date.day) < (ppt_end_date.month, ppt_end_date.day) else 0)
    )

    effective_xirr = xirr * 0.5 if remaining_ppt > 0 else xirr

    current_fund_value = 0.0
    for yr in range(years_paid):
        years_since = today.year - (commencement.year + yr)
        if (today.month, today.day) < (commencement.month, commencement.day):
            years_since -= 1
        current_fund_value += annual_premium * ((1 + xirr) ** max(0, years_since))

    future_value_paid_premium = current_fund_value * ((1 + effective_xirr) ** (remaining_ppt + remaining_term))

    monthly_sip = annual_premium / 12
    sip_months = remaining_ppt * 12

    def sip_fv(monthly, rate, months):
        r_m = rate / 12
        if r_m == 0 or months <= 0:
            return monthly * max(months, 0)
        return monthly * (((1 + r_m) ** months - 1) / r_m)

    large_cap_sip_at_ppt = sip_fv(monthly_sip, large_cap_rate, sip_months)
    baf_sip_at_ppt = sip_fv(monthly_sip, baf_rate, sip_months)

    large_cap_sip_fv = large_cap_sip_at_ppt * ((1 + lumpsum_growth_rate) ** remaining_term)
    baf_sip_fv = baf_sip_at_ppt * ((1 + baf_rate) ** remaining_term)

    alt_total_large_cap = future_value_paid_premium + large_cap_sip_fv
    alt_total_baf = future_value_paid_premium + baf_sip_fv

    return {
        'policy_name': policy.get('policy_name', 'ULIP'),
        'annual_premium': annual_premium,
        'xirr': round(xirr * 100, 2),
        'effective_xirr': round(effective_xirr * 100, 2),
        'years_paid': years_paid,
        'remaining_ppt': remaining_ppt,
        'remaining_term_years': remaining_term,
        'current_fund_value': round(current_fund_value, 2),
        'future_value_paid_premium': round(future_value_paid_premium, 2),
        'total_premium_paid': annual_premium * years_paid,
        'total_premium_remaining': annual_premium * remaining_ppt,
        'ulip_maturity_value': float(policy.get('maturity_value', 0) or 0),
        'large_cap_sip_at_ppt': round(large_cap_sip_at_ppt, 2),
        'baf_sip_at_ppt': round(baf_sip_at_ppt, 2),
        'large_cap_sip_fv': round(large_cap_sip_fv, 2),
        'baf_sip_fv': round(baf_sip_fv, 2),
        'alt_total_large_cap': round(alt_total_large_cap, 2),
        'alt_total_baf': round(alt_total_baf, 2),
        'lumpsum_growth_years': remaining_term,
    }


def update_ulip_current_values(state: ClientState):
    """
    Back-calculate ULIP current values and store opportunity-cost analytics.
    Runs conditionally: if no ULIP exists, returns without changes.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: update_ulip_current_values \n")
    print("Back-calculating ULIP current values + opportunity-cost analytics...\n")

    client_data = state.get('client_data', {})
    retirement_investments = client_data.get('investment_details', {}).get('retirement_investments', {})
    ulips = retirement_investments.get('ulip', [])

    if not isinstance(ulips, list) or not ulips:
        print("No ULIPs found.\n")
        print("--------------------------"*6)
        return {'client_data': client_data, 'ulip_opportunity_cost_data': {}}

    ulip_opportunity_cost_data = {}

    for i, policy in enumerate(ulips):
        try:
            # Single source of truth: opportunity-cost computation also gives current fund value.
            oc_data = calculate_ulip_opportunity_cost(policy)
            policy['inferred_xirr'] = round(oc_data.get('xirr', 0) / 100, 6)
            policy['current_value'] = oc_data.get('current_fund_value', policy.get('current_value', 0))

            policy_key = policy.get('policy_name') or f'ULIP_{i+1}'
            if policy_key in ulip_opportunity_cost_data:
                policy_key = f"{policy_key}_{i+1}"
            ulip_opportunity_cost_data[policy_key] = oc_data
        except Exception as e:
            print(f"ULIP #{i+1} skipped due to error: {e}")
            policy['current_value'] = policy.get('current_value', 0)

    print(f"Updated ULIP current values for {len(ulips)} policy(ies).\n")
    print("--------------------------"*6)
    return {
        'client_data': client_data,
        'ulip_opportunity_cost_data': ulip_opportunity_cost_data
    }


#def check_and_allocate_emergency_fund(state: ClientState):
#    """
#    Checks if the client has an adequate emergency fund (6x current monthly expenses).
#    If not, allocates funds from liquid assets to create one and updates asset values.
#    
#    Purpose:
#        - Check if 'emergency_fund_maintained' exists in financial summary
#        - Verify if existing emergency fund is 6x current monthly expenses
#        - If insufficient, allocate from liquid assets (prioritize lower-priority assets)
#        - Update asset values after allocation
#        - Ensure client has financial safety net before other goals
    
#    Returns:
#        Updated state with:
#        - emergency_fund_status: dict with current fund, required amount, and allocation details
#        - Updated liquid_assets with reduced values
#        - Updated liquid_pool with new total
#    """
#    print("--------------------------"*6)
#    print("\n")
#    print("Node: check_and_allocate_emergency_fund \n")
#    print("Checking and allocating emergency fund (6x monthly expenses)... \n")
    
#    client_data = state['client_data']
#    financial_summary = client_data['investment_details']['financial_summary'][0]
    
#    # Calculate required emergency fund
#    monthly_expenses = (financial_summary['monthly_expenses_excl_emis'] + 
#                       financial_summary['miscellaneous_kids_education_expenses_monthly'] + 
#                       (financial_summary['annual_vacation_expenses'] / 12))
    
#    required_emergency_fund = monthly_expenses * 6
    
#    # Check if emergency_fund_maintained exists
#    has_existing_fund = 'emergency_fund_maintained' in financial_summary
#    current_emergency_fund = financial_summary.get('emergency_fund_maintained', 0) if has_existing_fund else 0
    
#    # Determine if existing fund meets the requirement
#    is_adequate = current_emergency_fund >= required_emergency_fund if has_existing_fund else False
#    shortage = max(0, required_emergency_fund - current_emergency_fund)
    
#    allocation_details = {
#        'monthly_expenses': round(monthly_expenses, 2),
#        'required_emergency_fund': round(required_emergency_fund, 2),
#        'existing_emergency_fund': round(current_emergency_fund, 2),
#        'has_existing_fund': has_existing_fund,
#        'is_adequate': is_adequate,
#        'shortage': round(shortage, 2),
#        'assets_allocated': []
#    }
    
#    # If emergency fund exists and is adequate, no action needed
#    if is_adequate:
#        print(f"✓ Emergency fund exists and is adequate:")
#        print(f"  Current fund: {current_emergency_fund} >= Required: {required_emergency_fund}\n")
#        print("--------------------------"*6)
#        return {
#            'emergency_fund_status': allocation_details,
#            'liquid_assets': state.get('liquid_assets', []),
#            'liquid_pool': state.get('liquid_pool', 0)
#        }
    
    # If emergency fund exists but is insufficient
#    if has_existing_fund and current_emergency_fund > 0:
#        print(f"⚠ Emergency fund exists but is INSUFFICIENT:")
#        print(f"  Current fund: {current_emergency_fund}")
#        print(f"  Required (6x expenses): {required_emergency_fund}")
#        print(f"  Shortage: {shortage}\n")
    
#    # If no emergency fund exists at all
#    if not has_existing_fund or current_emergency_fund == 0:
#        print(f"✗ No emergency fund exists or is zero:")
#        print(f"  Creating emergency fund of: {required_emergency_fund}\n")
    
#    # Emergency fund is insufficient or missing - allocate from liquid assets
#    liquid_assets = state.get('liquid_assets', [])
#    liquid_pool = state.get('liquid_pool', 0)
#    remaining_shortage = shortage
#    updated_liquid_pool = liquid_pool
    
#    print(f"Allocating {shortage} from liquid assets...\n")
    
#    # Allocate from liquid assets (prioritize mutual funds, then direct equity, then others)
#    allocation_priority = ['mutual_funds', 'direct_equity', 'reits', 'fixed_deposits', 'other_investments']
    
#    for asset_item in liquid_assets:
#        if remaining_shortage <= 0:
#            break
            
#        asset_type = list(asset_item.keys())[0]
#        asset_data = asset_item[asset_type]
        
#        if asset_type not in allocation_priority:
#            continue
        
#        # Get current asset value
#        current_value = asset_data.get('current_value') or asset_data.get('portfolio_value') or asset_data.get('principal_amount', 0)
        
#        if current_value <= 0:
#            continue
        
#        # Allocate what we need (or what's available, whichever is less)
#        allocated_amount = min(remaining_shortage, current_value)
        
#        # Update asset value
#        new_asset_value = current_value - allocated_amount
#        if 'current_value' in asset_data:
#            asset_data['current_value'] = new_asset_value
#        elif 'portfolio_value' in asset_data:
#            asset_data['portfolio_value'] = new_asset_value
#        elif 'principal_amount' in asset_data:
#            asset_data['principal_amount'] = new_asset_value
        
#        # Update liquid pool
#        updated_liquid_pool -= allocated_amount
#        remaining_shortage -= allocated_amount
        
#        # Track allocation
#        allocation_details['assets_allocated'].append({
#            'asset_type': asset_type,
#            'asset_id': asset_data.get('asset_id'),
#            'allocated_amount': round(allocated_amount, 2),
#            'remaining_value': round(new_asset_value, 2)
#        })
        
#        print(f"  Allocated {allocated_amount} from {asset_type}")
    
    # Update emergency fund to required amount
#    financial_summary['emergency_fund_maintained'] = required_emergency_fund
#    allocation_details['emergency_fund_maintained_final'] = round(required_emergency_fund, 2)
#    allocation_details['total_allocated_from_assets'] = round(shortage - remaining_shortage, 2)
#    allocation_details['unmet_shortage'] = round(remaining_shortage, 2)
    
#    print(f"\n✓ Emergency fund allocation complete:")
#    print(f"  Total allocated from assets: {shortage - remaining_shortage}")
#    print(f"  Final emergency fund: {required_emergency_fund}")
#    if remaining_shortage > 0:
#        print(f"  ⚠ Unmet shortage: {remaining_shortage} (insufficient liquid assets)")
#    print(f"  Updated liquid pool: {updated_liquid_pool}\n")
#    print("--------------------------"*6)
    
#    return {
#        'emergency_fund_status': allocation_details,
#        'liquid_assets': liquid_assets,
#        'liquid_pool': max(0, round(updated_liquid_pool, 2))
#    }
"""

# def asset_basket_classification(state: ClientState):
#     """
#     Classifies all client investment instruments into liquid, fixed, or retirement assets, 
#     and assigns each instrument a unique asset ID and tag.

#     Purpose:
#         - Tags each investment with "asset_tag" (liquid, fixed, or retirement).
#         - Assigns a unique "asset_id" to every instrument.
#         - Produces categorized lists of instruments for further analysis.
#     """
#     client_data=state['client_data']
#     asset_basket=client_data['investment_details']
#     i=0
#     for asset in asset_basket:
        
#         for instrument in asset_basket[f"{asset}"]:
#             if asset=='real_estate_investment':
#                 instrument['asset_tag']='fixed_asset'
#                 instrument['asset_id']=i
#             if asset=='retirement_investments':
#                 for retirement_instrument in asset_basket[asset][f'{instrument}']:
#                     retirement_instrument['asset_tag']='retirement_asset'
#                     retirement_instrument['asset_id']=i
#                     i+=1
#             if asset=='bonds':
#                 instrument['asset_tag']='fixed_asset'
#                 instrument['asset_id']=i
#             if asset=='mutual_funds':
#                 instrument['asset_tag']='liquid_asset'
#                 instrument['asset_id']=i
#             if asset=='direct_equity':
#                 instrument['asset_tag']='liquid_asset'
#                 instrument['asset_id']=i
#             if asset=='reits':
#                 instrument['asset_tag']='liquid_asset'
#                 instrument['asset_id']=i
#             if asset=='pms_aif':
#                 instrument['asset_tag']='fixed_asset'
#                 instrument['asset_id']=i
#             if asset=='esops':
#                 instrument['asset_tag']='fixed_asset'
#                 instrument['asset_id']=i
#             if asset=='ncd_govt':
#                 instrument['asset_tag']='fixed_asset'
#                 instrument['asset_id']=i
#             if asset=='fixed_deposits':
#                 instrument['asset_tag']='fixed_asset'
#                 instrument['asset_id']=i
#             i+=1

#     liquid_assets=[]
#     fixed_assets=[]
#     retirement_assets=[]
#     asset_basket=client_data['investment_details']  
#     for asset in asset_basket:
        
#         if asset=='financial_summary':
#             continue       
#         for instrument in asset_basket[f"{asset}"]:
#             # print(f"instrument: {instrument}")
#             if asset=='retirement_investments':
#                 for retirement_instrument in asset_basket[asset][f'{instrument}']:
#                         #print(asset_basket[asset][f'{instrument}'])
#                         # print(f"retirement instrument: {retirement_instrument}")
#                         if retirement_instrument['asset_tag']=='retirement_asset':
#                             retirement_assets.append({f'{instrument}':retirement_instrument})
                        
#             elif instrument['asset_tag']=='liquid_asset':
#                 #liquid_assets[f'{asset}']=instrument
#                 liquid_assets.append({f'{asset}':instrument})

#             elif instrument['asset_tag']=='fixed_asset':
#                 #fixed_assets[f'{asset}']=instrument
#                 fixed_assets.append({f'{asset}':instrument})
            
#     return {'retirement_assets': retirement_assets, 'liquid_assets': liquid_assets, 'fixed_assets': fixed_assets}

def asset_basket_classification(state: ClientState):
    """
    Classifies all client investment instruments into liquid, fixed, or retirement assets, 
    and assigns each instrument a unique asset ID and tag.

    Purpose:
        - Tags each investment with "asset_tag" (liquid, fixed, or retirement).
        - Assigns a unique "asset_id" to every instrument.
        - Produces categorized lists of instruments for further analysis.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: asset_basket_classification \n")
    print("Classifing assets into three baskets: \n 1. Retirement  \n 2. Liquid \n 3. Fixed \n")
    # Define asset classification mapping
    ASSET_CLASSIFICATION = {
        'real_estate_investment': 'fixed_asset',
        'bonds': 'fixed_asset',
        'pms_aif': 'fixed_asset',
        'esops': 'fixed_asset',
        'ncd_govt': 'fixed_asset',
        'fixed_deposits': 'liquid_asset',
        'mutual_funds': 'liquid_asset',
        'direct_equity': 'liquid_asset',
        'reits': 'liquid_asset',
        'retirement_investments': 'retirement_asset',
        'other_investments': 'liquid_asset'}
    
    client_data = state['client_data']
    asset_basket = client_data['investment_details']
    
    # Initialize result containers
    liquid_assets = []
    fixed_assets = []
    retirement_assets = []
    
    asset_id = 0
    
    for asset_type, instruments in asset_basket.items():
        # Skip non-investment entries
        if asset_type == 'financial_summary' or asset_type not in ASSET_CLASSIFICATION:
            continue
        
        asset_tag = ASSET_CLASSIFICATION[asset_type]
        
        # Handle retirement investments specially (nested structure)
        if asset_type == 'retirement_investments':
            for retirement_account_name, retirement_instruments in instruments.items():
                if not isinstance(retirement_instruments, list):
                    continue
                    
                for retirement_instrument in retirement_instruments:
                    if not isinstance(retirement_instrument, dict):
                        continue
                    
                    retirement_instrument['asset_tag'] = 'retirement_asset'
                    retirement_instrument['asset_id'] = asset_id
                    retirement_assets.append({retirement_account_name: retirement_instrument})
                    asset_id += 1
        else:
            # Handle regular investments
            if not isinstance(instruments, list):
                continue
                
            for instrument in instruments:
                if not isinstance(instrument, dict):
                    continue
                
                instrument['asset_tag'] = asset_tag
                instrument['asset_id'] = asset_id
                
                # Categorize based on tag
                if asset_tag == 'liquid_asset':
                    liquid_assets.append({asset_type: instrument})
                elif asset_tag == 'fixed_asset':
                    fixed_assets.append({asset_type: instrument})
                
                asset_id += 1
    
    classification={
        'retirement_assets': retirement_assets,
        'liquid_assets': liquid_assets,
        'fixed_assets': fixed_assets
    }
    print(f"classification: {classification}\n")
    print("--------------------------"*6)
    return classification 

# def calculate_liquid_asset_value(state: ClientState):
#     """
#     Computes the total value of all liquid assets in the client's portfolio.
#     Purpose:
#         Iterates through all liquid assets, extracts their current/portfolio values, 
#         and produces a consolidated liquid pool value.
#     """
#     assets_list=state['liquid_assets']
#     total_asset_value = 0.0

#     for asset_item in assets_list:
#         # Skip any empty or invalid entries in the list
#         if not asset_item or not isinstance(asset_item, dict):
#             continue

#         # Extract the inner dictionary which holds the actual asset data
#         asset_data = list(asset_item.values())[0]

#         # Find the asset's value, checking different possible keys.
#         # Defaults to 0 if the value is None or the key doesn't exist.
#         current_value = asset_data.get('current_value') or asset_data.get('portfolio_value') or 0

#         # Ensure the value is a number before adding, defaulting to 0 otherwise
#         if not isinstance(current_value, (int, float)):
#             current_value = 0

#         # Add the value to the total
#         total_asset_value += current_value

#     return {"liquid_pool": total_asset_value}

def calculate_liquid_asset_value(state: ClientState):
    """
    Computes the total value of all liquid assets in the client's portfolio.
    
    Purpose:
        Iterates through all liquid assets, extracts their current/portfolio values, 
        and produces a consolidated liquid pool value.
    
    Returns:
        dict: Contains 'liquid_pool' with total value
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_liquid_asset_value \n")
    print("Calculating the total value of all liquid assets... \n")
    assets_list = state.get('liquid_assets', [])
    
    # Validate input
    if not isinstance(assets_list, list):
        print("Error in node calculate liquid asset value")

        return {
            'liquid_pool': 0.0,
            'error': 'Invalid assets_list format',
            'calculation_details': []
        }
    
    total_asset_value = 0.0
    calculation_details = []
    skipped_assets = []
    
    # Priority order for value keys
    VALUE_KEYS = ['current_value', 'portfolio_value', 'market_value', 'value', 'principal_amount']
    
    for idx, asset_item in enumerate(assets_list):
        # Validate asset item structure


        if not asset_item or not isinstance(asset_item, dict):
            skipped_assets.append({'index': idx, 'reason': 'Invalid or empty asset item'})
            continue
        
        # Handle empty dictionaries
        if not asset_item:
            skipped_assets.append({'index': idx, 'reason': 'Empty asset dictionary'})
            continue
        
        # Extract asset type and data 
        try:
            asset_type = list(asset_item.keys())[0]
            asset_data = asset_item[asset_type]
            
            if not isinstance(asset_data, dict):
                skipped_assets.append({
                    'index': idx,
                    'asset_type': asset_type,
                    'reason': 'Asset data is not a dictionary'
                })
                continue
            
            if asset_type=='other_investments':
                asset_data['value']=calculate_current_value(asset_data)
                  
        except (IndexError, KeyError) as e:
            skipped_assets.append({'index': idx, 'reason': f'Error extracting asset data: {e}'})
            continue
        
        # Extract value using priority order
        asset_value = None
        value_key_used = None
        
        for key in VALUE_KEYS:
            value = asset_data.get(key)
            if value is not None and isinstance(value, (int, float)) and value > 0:
                asset_value = float(value)
                value_key_used = key
                break
        
        # Handle case where no valid value found
        if asset_value is None:
            skipped_assets.append({
                'index': idx,
                'asset_type': asset_type,
                'asset_id': asset_data.get('asset_id'),
                'reason': 'No valid value found in expected keys'
            })
            continue
        
        # Add to total
        total_asset_value += asset_value
        
        # Track calculation details for transparency/debugging
        calculation_details.append({
            'asset_type': asset_type,
            'asset_id': asset_data.get('asset_id'),
            'value': asset_value,
            'value_key': value_key_used
        })
    
    print(f" Liquid pool: {round(total_asset_value, 2)}\n")
    print("--------------------------"*6)
    return {'liquid_pool': round(total_asset_value, 2)}


def calculate_term_insurance_requirement(state: ClientState):
    """
    Calculates the total term insurance cover required for the client
    based on income replacement, liabilities, education costs and
    existing cover / liquid assets.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_term_insurance_requirement \n")
    print("Calculating term insurance requirement...\n")

    client_info = state.get('required_retirement_corpus', {}).get('client_info', {})
    monthly_expenses = client_info.get('current_monthly_expenses', 0)
    inflation_rate = 0.06
    pv_of_expenses = int(monthly_expenses * 12 / inflation_rate) if inflation_rate else 0

    kids_education_cost = sum(
        edu.get('future_cost', 0)
        for edu in state.get('client_data', {}).get('education_planning_summary', [])
    )

    current_liabilities = sum(
        liability.get('outstanding_balance', 0)
        for liability in state.get('liabilities', [])
    )

    client_data = state.get('client_data', {})
    existing_cover = sum(
        policy.get('maturity_value', 0)
        for policy in client_data.get('insurance_policies', [])
    )
    for policy in client_data.get('life_insurance', []):
        existing_cover += policy.get('coverage_value', 0) or 0
    for policy in client_data.get('investment_details', {}).get('lic_policies', []):
        existing_cover += policy.get('maturity_value', 0) or 0

    liquidable_assets = state.get('liquid_pool', 0)

    total_term_required = (
        pv_of_expenses
        + kids_education_cost
        + current_liabilities
        - existing_cover
        - liquidable_assets
    )
    total_term_required = max(total_term_required, 0)

    term_insurance_summary = {
        "pv_of_expenses": pv_of_expenses,
        "kids_education_cost": kids_education_cost,
        "current_liabilities": current_liabilities,
        "existing_cover": existing_cover,
        "liquidable_assets": liquidable_assets,
        "total_term_required": total_term_required,
    }

    print(f" Term insurance required: {total_term_required:,.0f}\n")
    print("--------------------------"*6)
    return {"term_insurance_summary": term_insurance_summary}


def calculate_fixed_assets_value(state: ClientState):
    """
    Calculates the total current value of fixed assets from a list.
    The function approximates the current value based on the most relevant
    field available for each asset type (e.g., principal for FDs, vested
    value for ESOPs).
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_fixed_assets_value \n")
    print("Calculating total value of all the fixed assets... \n")
    assets_list=state.get('fixed_assets', [])
    total_fixed_asset_value = 0.0

    for asset_item in assets_list:
        # Skip any empty or malformed entries in the list
        if not asset_item or not isinstance(asset_item, dict):
            continue

        # Each item is a dict with one key (the asset type), so we get its value
        asset_data = list(asset_item.values())[0]
        current_value = 0

        # Determine the value based on the asset type and available fields
        if 'current_market_value' in asset_data:
            # For Real Estate
            current_value = asset_data.get('current_market_value')
        elif 'investment_amount' in asset_data:
            # For Bonds
            current_value = asset_data.get('investment_amount')
        elif 'vested_esops_value' in asset_data:
            # For ESOPs, only consider the vested portion
            current_value = asset_data.get('vested_esops_value')
        elif 'principal_amount' in asset_data:
            # For Fixed Deposits, use the principal as the current value
            current_value = asset_data.get('principal_amount')
        elif 'current_value' in asset_data:
            # For PMS/AIF and other similar assets
            current_value = asset_data.get('current_value')

        # Add to the total, ensuring the value is a number
        if isinstance(current_value, (int, float)):
            total_fixed_asset_value += current_value
    
    print(f"fixed asset pool: {total_fixed_asset_value}\n")
    print("--------------------------"*6)
    return {"fixed_asset_pool": total_fixed_asset_value}

def calculate_asset_percentages_and_ratios(state: ClientState): 
    """
    Analyze client’s assets and financial habits to compute allocation, ratios, and behavior flags.
    Purpose:
        - Calculate % allocation across retirement, liquid, and fixed assets.
        - Assess liquidity (ability to meet short-term needs).
        - Evaluate flexibility (redeemable/market-linked vs locked-in/fixed assets).
        - Analyze spending & saving habits with age-based thresholds and red-flag warnings.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: calculate_asset_percentages_and_ratios \n")
    print("Checking financial health and calculating asset percentages... \n")
    retirement_assets=state['retirement_assets']
    liquid_assets=state['liquid_assets']
    fixed_assets=state['fixed_assets']
    financial_info=state['client_data']['investment_details']['financial_summary']
    age=state['client_data']['client_data']['client_age']

    def get_retirement_value(asset):
        key = list(asset.keys())[0]
        val = asset[key]
        if key == 'ulip':
            return 0
        elif key == 'epf':
            return val['current_value']
        elif key == 'ppf':
            return val['current_value']
        elif key == 'nps':
            return val['current_value']
        else:
            return 0

    def get_liquid_value(asset):
        key = list(asset.keys())[0]
        val = asset[key]
        if key == 'mutual_funds':
            if val['current_value'] is not None:
                return val['current_value']
            elif val['sip_amount'] is not None:
                return val['sip_amount'] * 12  # Estimate annual value
            else:
                return 0
        elif key == 'direct_equity':
            return val['portfolio_value']
        elif key == 'reits':
            return val['current_value']
        else:
            return 0

    def get_fixed_value(asset):
        key = list(asset.keys())[0]
        val = asset[key]
        if key == 'real_estate_investment':
            return val['current_market_value']
        elif key == 'bonds':
            return val['investment_amount']
        elif key == 'pms_aif':
            return val['current_value']
        elif key == 'esops':
            return val.get('vested_esops_value', 0) + val.get('unvested_esops_value', 0)
        elif key == 'fixed_deposits':
            return val['principal_amount']
        else:
            return 0

    # Calculate category totals
    retirement_total = sum(get_retirement_value(a) for a in retirement_assets)
    liquid_total = sum(get_liquid_value(a) for a in liquid_assets)
    fixed_total = sum(get_fixed_value(a) for a in fixed_assets)
    grand_total = retirement_total + liquid_total + fixed_total

    # Calculate category percentages
    retirement_percent = (retirement_total / grand_total) * 100 if grand_total != 0 else 0
    liquid_percent = (liquid_total / grand_total) * 100 if grand_total != 0 else 0
    fixed_percent = (fixed_total / grand_total) * 100 if grand_total != 0 else 0

    # Calculate individual asset percentages within each category
    retirement_assets_percent = {}
    for a in retirement_assets:
        key = list(a.keys())[0]
        if key == 'ulip':
            continue
        val = get_retirement_value(a)
        retirement_assets_percent[key] = (val / retirement_total) * 100 if retirement_total != 0 else 0

    liquid_assets_percent = {}
    for a in liquid_assets:
        key = list(a.keys())[0]
        val = get_liquid_value(a)
        liquid_assets_percent[key] = (val / liquid_total) * 100 if liquid_total != 0 else 0

    fixed_assets_percent = {}
    for a in fixed_assets:
        key = list(a.keys())[0]
        val = get_fixed_value(a)
        fixed_assets_percent[key] = (val / fixed_total) * 100 if fixed_total != 0 else 0

    # 1. Liquidity Ratio calculation
    liquidity_ratio = liquid_total / grand_total if grand_total != 0 else 0
    liquidity_flag = 'illiquidity' if liquidity_ratio < 0.15 else 'liquidity ok'

    # 2. Flexibility calculation
    fixed_income_and_real_estate = 0
    market_linked_redeemable = 0

    # Calculate fixed income and real estate assets
    for a in fixed_assets:
        key = list(a.keys())[0]
        if key == 'real_estate_investment':
            fixed_income_and_real_estate += get_fixed_value(a)
        elif key in ['bonds', 'fixed_deposits']:
            fixed_income_and_real_estate += get_fixed_value(a)

    for a in retirement_assets:
        key = list(a.keys())[0]
        val = a[key]
        if key in ['epf', 'ppf']:
            fixed_income_and_real_estate += get_retirement_value(a)
        elif key == 'nps':
            # NPS annuity portion considered fixed income
            annuity_pct = val.get('annuity_allocation_pct', 0)
            if annuity_pct > 0:
                fixed_income_and_real_estate += get_retirement_value(a) * annuity_pct
            # Equity portion considered market linked
            market_linked_redeemable += get_retirement_value(a) * (1 - annuity_pct)
    # All liquid assets are market linked/redeemable
    market_linked_redeemable += liquid_total
    
    # Add PMS/AIF to market linked assets
    for a in fixed_assets:
        key = list(a.keys())[0]
        if key in ['pms_aif', 'esops']:
            market_linked_redeemable += get_fixed_value(a)

    flexibility = 'medium to high flexibility' if market_linked_redeemable > fixed_income_and_real_estate else 'low flexibility'

    # 3. Spending Behavior calculation
    info = financial_info[0]
    monthly_salary = info.get('monthly_salary', 0)
    monthly_expenses = info.get('monthly_expenses_excl_emis', 0) + info.get('miscellaneous_kids_education_expenses_monthly', 0)
    other_income = info.get('other_income(rental/interest/other)', 0)
    annual_vacation = info.get('annual_vacation_expenses', 0)
    
    total_monthly_income = monthly_salary + other_income
    total_monthly_expenses = monthly_expenses + (annual_vacation / 12)
    monthly_saving = total_monthly_income - total_monthly_expenses
    
    saving_ratio = monthly_saving / total_monthly_income if total_monthly_income > 0 else 0
    expense_ratio = total_monthly_expenses / total_monthly_income if total_monthly_income > 0 else 0

    red_flag = False
    if ((saving_ratio < 0.2 and age < 40) or 
        (saving_ratio < 0.3 and age >= 40) or 
        (expense_ratio > 0.7)):
        red_flag = True

    spending_behavior = {
        'saving_ratio': saving_ratio,
        'expense_ratio': expense_ratio,
        'red_flag': red_flag
    }

    result={
        'category_percentage': {
            'retirement': round(retirement_percent, 2),
            'liquid': round(liquid_percent, 2),
            'fixed': round(fixed_percent, 2)
        },
        'retirement_assets_percent': retirement_assets_percent,
        'liquid_assets_percent': liquid_assets_percent,
        'fixed_assets_percent': fixed_assets_percent,
        'liquidity_ratio': liquidity_ratio,
        'liquidity_flag': liquidity_flag,
        'flexibility': flexibility,
        'spending_behavior': spending_behavior
    }
    
    print(f"financial overview: {result}\n")
    print("--------------------------"*6)
    return {'financial_overview': result} 

def invest_monthly_surplus(state: ClientState):
    """
    Invest monthly_surplus into three components:
      - 30% -> Debt funds/BAFs for 5 years
      - 40% -> Hybrid/Equity MF for 10 years
      - 30% -> Equity MF or NPS until retirement_age

    Returns a JSON string with details and future values (assumes end-of-month SIPs).
    Uses today's date (datetime.date.today()) as start.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: invest_monthly_surplus \n")
    print("Investing the left monthly surplus towards suitable investment instruments... \n")
    # print("Node: invest_monthly_surplus")
    #monthly_surplus=state['final_unused_monthly_surplus'] state['optimal_loan_allocation']['unused_monthly_surplus']
    #monthly_surplus=state['optimal_loan_allocation']['unused_monthly_surplus']
    monthly_surplus=state['optimal_goal_allocation']['ending_monthly_surplus']
    age = state['client_data']['client_data']['client_age']
    retirement_age = state['client_data']['client_data']['retirement_age']

    # --- Configuration: chosen constant annual rates (modifiable) ---
    rate_debt = 0.07    # 7.0% p.a. for Debt (5-year)
    rate_hybrid = 0.11  # 11.0% p.a. for Hybrid (10-year)
    rate_equity = 0.11  # 11.0% p.a. for Equity/NPS until retirement (blended conservative)

    # --- allocations ---
    alloc = {
        "debt": 0.30,
        "hybrid": 0.40,
        "equity_nps": 0.30
    }

    today = date.today()
    current_year = today.year

    # Determine durations in months & maturity years
    years_debt = 5
    months_debt = years_debt * 12
    maturity_debt_year = current_year + years_debt

    years_hybrid = 10
    months_hybrid = years_hybrid * 12
    maturity_hybrid_year = current_year + years_hybrid

    years_equity = retirement_age - age
    if years_equity < 0:
        # Already at/after retirement: treat as zero-duration
        years_equity = 0
    months_equity = years_equity * 12
    maturity_equity_year = current_year + years_equity

    # monthly contributions
    c_debt = monthly_surplus * alloc["debt"]
    c_hybrid = monthly_surplus * alloc["hybrid"]
    c_equity = monthly_surplus * alloc["equity_nps"]

    # compute FVs at their maturation points
    fv_debt = fv_monthly(c_debt, rate_debt, months_debt)
    fv_hybrid = fv_monthly(c_hybrid, rate_hybrid, months_hybrid)
    fv_equity = fv_monthly(c_equity, rate_equity, months_equity)

    # invested amounts (sum of contributions) for transparency
    invested_debt = c_debt * months_debt
    invested_hybrid = c_hybrid * months_hybrid
    invested_equity = c_equity * months_equity

    # totals
    total_invested = invested_debt + invested_hybrid + invested_equity
    total_fv = fv_debt + fv_hybrid + fv_equity

    result = {
        "input": {
            "leftover_monthly_surplus": monthly_surplus,
            "age": age,
            "retirement_age": retirement_age,
            "start_date": today.isoformat()
        },
        "assumptions": {
            "rate_debt_p_a": rate_debt,
            "rate_hybrid_p_a": rate_hybrid,
            "rate_equity_nps_p_a": rate_equity,
            "allocation": alloc,
            "compounding": "monthly (SIP, payments at month end)"
        },
        "components": {
            "debt": {
                "monthly_contribution": round(c_debt, 2),
                "investment_duration_years": years_debt,
                "maturity_year": maturity_debt_year,
                "months": months_debt,
                "total_contributed": round(invested_debt, 2),
                "future_value_at_maturity": round(fv_debt, 2)
            },
            "hybrid": {
                "monthly_contribution": round(c_hybrid, 2),
                "investment_duration_years": years_hybrid,
                "maturity_year": maturity_hybrid_year,
                "months": months_hybrid,
                "total_contributed": round(invested_hybrid, 2),
                "future_value_at_maturity": round(fv_hybrid, 2)
            },
            "equity_nps": {
                "monthly_contribution": round(c_equity, 2),
                "investment_duration_years": years_equity,
                "maturity_year": maturity_equity_year,
                "months": months_equity,
                "total_contributed": round(invested_equity, 2),
                "future_value_at_maturity": round(fv_equity, 2)
            }
        },
        "summary": {
            "total_contributed": round(total_invested, 2),
            "total_future_value": round(total_fv, 2)
        }
    }
    print(f"Suggested Investment Plan for left monthly surplus: {result}\n")
    print("--------------------------"*6)
    state['extra_monthly_surplus_investment_plan']=result
    return state

def freed_emi_by_year(state: ClientState):
    """
    Returns {year: total_monthly_emi_freed} based on each loan's *natural* closure date.
    Notes:
      - Ignores prepayment/penalty windows; uses current EMI schedule.
      - Values are the *monthly EMI amounts* that become available after closure.
    """
    print("--------------------------"*6)
    print("\n")
    print("Node: freed_emi_by_year \n")
    print("Considering the loan closing naturally: calculating the closing year and free amount... \n")
    liabilities = state.get('liabilities', []) or []
    loans_exist = True if liabilities and sum([x['outstanding_balance'] for x in liabilities]) > 0 else False

    if loans_exist==False: 
        return {'freed_timeline': [], 'liability_allocation': [], 'loans_exist': loans_exist }

    today = date.today()
    year=today.year
    month=today.month
    day=today.day
    data_str=f"{year}-{month}-{day}"

    freed: dict[int, float] = {}
    for loan in liabilities:
        P = float(loan["outstanding_balance"])
        r_annual = float(loan["interest_rate"])
        emi = float(loan["emi_amount"])

        n_months = months_to_close(P, r_annual, emi)
        if n_months is None:
            continue

        close_dt = _add_months(today, n_months)
        freed[close_dt.year] = freed.get(close_dt.year, 0.0) + emi 

    result=present_loans_no_allocation(liabilities, date.today())
    
    print(f"Loan detail: {result}\n")
    print("--------------------------"*6)
    return {'freed_timeline': [freed], 'liability_allocation': [result], 'loans_exist': loans_exist}

def check_for_kid(state: ClientState):
    return state['client_data']['client_data']['if_any_kids']

def check_for_pre_payment(state: ClientState):
    """
    Convergence-based loop controller for the plan_prepayments cycle.

    Loops back to plan_prepayments while:
    - EMI_allocation is True (at least one prepayment iteration has run), AND
    - The change in total interest_saved between the last two iterations > ₹500, AND
    - We have not exceeded 8 iterations (safety cap)

    Stops and routes to choose_optimal_strategy once converged or cap reached.
    """
    CONVERGENCE_THRESHOLD = 500.0   # ₹500 change in total interest_saved = converged
    MAX_ITERATIONS = 8

    def _total_saved(alloc: dict) -> float:
        return sum(
            float(l.get('interest_saved', 0) or 0)
            for l in alloc.get('per_loan', [])
            if isinstance(l.get('interest_saved'), (int, float))
        )

    # EMI_allocation (no 'd') is set by plan_goals to signal prepayment is warranted.
    # loan_prepayed_times counts how many plan_prepayments iterations have run.
    n_prepay = len(state.get('liability_allocation', []))
    prepay_ran = state.get('loan_prepayed_times', 0) > 0
    emi_allocation_flag = state.get('EMI_allocation') == True  # set by plan_goals

    if emi_allocation_flag and not prepay_ran:
        # plan_goals says prepayment is warranted but we haven't run it yet
        return True

    # If no liquid pool was available, the only lever was the SIP step-up schedule,
    # which is fully captured in iteration 1. Further iterations just oscillate
    # as plan_goals reshuffles freed SIPs each time. Stop here.
    if emi_allocation_flag and prepay_ran:
        last_alloc = state.get('liability_allocation', [{}])[-1]
        if last_alloc.get('allocated_lump_sum', 0.0) == 0.0 and \
           last_alloc.get('assumptions', {}).get('liquid_pool_available', 0.0) == 0.0:
            # No lump sum was used — SIP step-up was the only lever, already captured
            return False  # stop loop, go to choose_optimal_strategy

    if emi_allocation_flag and prepay_ran:
        # liability_allocation[0] is baseline from freed_emi_by_year — skip it.
        # Only real prepayment iterations (index 1+) are compared for convergence.
        real_prepay_allocs = state.get('liability_allocation', [])[1:]
        if len(real_prepay_allocs) < 2:
            return False  # only 1 real iteration done — SIP step-up captured, stop

        prev = real_prepay_allocs[-2]
        curr = real_prepay_allocs[-1]
        delta = abs(_total_saved(curr) - _total_saved(prev))

        if delta >= CONVERGENCE_THRESHOLD and len(real_prepay_allocs) < MAX_ITERATIONS:
            return True  # not yet converged — loop again

        # Converged (or hit cap) — fall through to optimal selection

    # Always route to choose_optimal_strategy so it can set optimal_goal_allocation
    # in its returned dict (LangGraph ignores direct state mutations here).
    return False
