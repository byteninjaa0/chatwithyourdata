"""
Resource Allocation Strategy - Goals & Loans

What this file does:
This script implements sophisticated allocation strategies for funding goals and loan prepayments.
It optimizes resource utilization through greedy allocation, prepayment analysis, and multi-scenario optimization.

What this file contains and processes:
- plan_goals: Allocates liquid pool, monthly surplus, and freed SIPs to fund goals using greedy strategy with optional postponement up to max_postpone years
- plan_prepayments: Strategizes loan prepayment by splitting monthly surplus and lump sum evenly across eligible loans, capping allocations to avoid over-payment
- choose_optimal_strategy: Selects optimal allocation strategy across multiple scenarios by maximizing combined score of surplus ratio and interest savings
"""

# allocation nodes: plan_goals, plan_prepayments, choose_optimal_strategy
from Financial_Planning.Models.client_data_state import ClientState
from datetime import datetime, date
from Financial_Planning.Utilities.utility_functions import (apply_lumpsum_to_goal, apply_freed_sip_to_goal, apply_surplus_sip_to_goal, remaining_tenure, _add_months, calculate_future_value,
                                                         max_extra_payment, total_interest, _freed_by_year, _safe, sip_required, stepup_sip_required, recommend_stepup_sip_for_gap, calculate_ssy_future_value)
import copy
import pickle 
import os
import sys  
from Financial_Planning.RSU.webscrapper import load_rsu_market_data
from Financial_Planning.RSU.constants import get_rsu_growth_rate


def rsu_years_utilized_for_draw(
    tranche_details: list,
    goal_year: int,
    draw_start: float,
    draw_amount: float,
    usable_cap: float = 0.6,
) -> list[int]:
    """
    FIFO: vest years whose capped tranche slices overlap [draw_start, draw_start + draw_amount).
    """
    if draw_amount <= 0:
        return []
    draw_end = draw_start + draw_amount
    pos = 0.0
    years: list[int] = []
    sorted_tranches = sorted(
        (t for t in tranche_details if int(t["year"]) <= goal_year),
        key=lambda t: int(t["year"]),
    )
    for tranche in sorted_tranches:
        vest_year = int(tranche["year"])
        slice_usable = round(float(tranche["tranche_value_inr"]) * usable_cap, 2)
        slice_start = pos
        slice_end = pos + slice_usable
        if slice_end > draw_start and slice_start < draw_end:
            years.append(vest_year)
        pos = slice_end
    return years


def calculate_fv_after_one_year(funded_from: list, r_annual: float = 0.08) -> float:
    """
    Calculate the future value of current year allocations after 1 year.
    This accounts for:
    - Lumpsum invested today growing for 1 year
    - SIP installments made monthly during the year, each growing for different periods
    
    Args:
        funded_from: List of funding sources with their allocations
        r_annual: Annual rate of return (default 0.08 for 8%)
        
    Returns:
        Future value of all current year allocations after 1 year (0 if empty list)
    """
    if not funded_from:  # Handle empty list
        return 0
    
    r_monthly = r_annual / 12.0
    total_fv = 0
    
    for funding in funded_from:
        if funding.get('type') in ['lumpsum_from_liquid_partial']:
            # Lumpsum grows for 12 months
            principal = funding.get('principal_used_today', 0)
            fv = principal * ((1 + r_monthly) ** 12)
            total_fv += fv
            
        elif funding.get('type') in ['sip_from_partial_surplus', 'freed_sip']:
            # SIP: each monthly installment grows for different periods
            # Month 1 grows for 11 months, Month 2 for 10 months, ..., Month 12 for 0 months
            monthly_sip = funding.get('monthly_used', 0)
            sip_fv = 0
            for month in range(12):
                months_to_grow = 11 - month  # First SIP grows for 11 months, last for 0
                sip_fv += monthly_sip * ((1 + r_monthly) ** months_to_grow)
            total_fv += sip_fv
    
    return round(total_fv)

def project_ssy_accounts(state, ssy_tracker, goal_results, ssy_interest_rate=0.082):
    """
    Read-only projection of every Sukanya Samriddhi account to its maturity.

    plan_goals values an SSY account only in the year a goal draws on it, so
    an account no goal uses, or the balance left locked after a partial
    withdrawal, never gets a value at maturity. This records one, for display
    (the plan deck). It reads the same inputs apply_ssy_to_goal reads and
    uses the same calculate_ssy_future_value(), and changes nothing: not the
    tracker, not the goals, not any surplus or pool.

    Returns one entry per account:
        child_name, opening_date, contribution_end_year, maturity_year,
        annual_contribution, current_value, interest_rate,
        maturity_value            -- whole account at maturity, no withdrawals
        withdrawals               -- [{goal, year, amount}] the plan takes from it
        balance_at_maturity       -- what is left at maturity after those withdrawals
    """
    projections = []
    current_year = datetime.today().year
    children = state.get('client_data', {}).get('client_data', {}).get('children', []) or []
    for child in children:
        full_name = child.get('child_name', '')
        first_name = full_name.split(" ")[0]
        for inv in child.get('investments', []) or []:
            if str(inv.get('type', '')).upper() != 'SUKANYA SAMRIDDHI YOJANA':
                continue
            try:
                opening = datetime.strptime(inv.get('commencement_date'), '%Y-%m-%d').date()
                dob_text = child.get('child_dob')
                dob = datetime.strptime(dob_text, '%Y-%m-%d').date() if dob_text else opening
            except (TypeError, ValueError) as e:
                print(f"SSY projection skipped for {full_name}: {e}")
                continue
            maturity_year = opening.year + 21
            entry = {
                'child_name': full_name,
                'opening_date': opening.isoformat(),
                'contribution_end_year': opening.year + 15,
                'maturity_year': maturity_year,
                'annual_contribution': float(inv.get('annual_contribution') or 0),
                'current_value': float(inv.get('current_value') or 0),
                'interest_rate': ssy_interest_rate,
                'maturity_value': None,
                'withdrawals': [],
                'balance_at_maturity': None,
            }
            if maturity_year >= current_year:
                result = calculate_ssy_future_value(
                    current_value=inv.get('current_value') or 0,
                    annual_contribution=inv.get('annual_contribution') or 0,
                    account_opening_date=opening,
                    girl_child_dob=dob,
                    goal_target_year=maturity_year,
                    goal_type='other',
                    ssy_interest_rate=ssy_interest_rate,
                )
                entry['maturity_value'] = result.get('total_fv_at_goal')

            for goal in goal_results or []:
                note = goal.get('note')
                drawn_in = note.get('to_year') if isinstance(note, dict) and note.get('to_year') else goal.get('target_year')
                for src in goal.get('funded_from', []) or []:
                    if src.get('type') == 'ssy_funds' and src.get('source') == f'SSY account of {first_name}':
                        entry['withdrawals'].append({
                            'goal': goal.get('goal_name'),
                            'year': drawn_in,
                            'amount': src.get('amount_used'),
                        })

            tracked = (ssy_tracker or {}).get(first_name)
            if tracked:
                # Same growth step apply_ssy_to_goal uses for a locked balance.
                remaining = float(tracked.get('remaining_balance') or 0)
                years = maturity_year - int(tracked.get('last_withdrawal_year') or maturity_year)
                entry['balance_at_maturity'] = round(remaining * ((1 + ssy_interest_rate) ** max(years, 0)))
            else:
                entry['balance_at_maturity'] = entry['maturity_value']
            projections.append(entry)
    return projections


def plan_goals(state: ClientState):
    """
    Allocates available resources (liquid pool, monthly surplus, freed SIPs) 
    to fund client goals using a greedy strategy with optional postponement.
    Purpose:
        - Funds goals in order using a greedy allocation strategy:
            * Short horizon (≤ near_term_years): lumpsum → freed SIP → surplus SIP → lumpsum.
            * Long horizon: freed SIP → surplus SIP → lumpsum.
        - Allows postponement up to `max_postpone` years if gaps remain.
        - Tracks funding sources and updates global resource pools accordingly.
    """ 
    print("--------------------------"*6)
    print("\n")
    print("Node: plan_goals \n")
    print("Allocating Goals... \n") 
    updated_goals = copy.deepcopy(state['sorted_goals'])   #List[Dict[str, Any]],
    if state['EMI_allocated']: 
        monthly_surplus_init = round(state['monthly_surplus'] - state['used_monthly_surplus'][-1])
        liquid_pool_init = round(state['liquid_pool']-state['used_liquid_surplus'][-1])
        freed_sip_init = state['freed_timeline'][-1] if state['freed_timeline']!=[] else []
    else: 
        monthly_surplus_init = round(state['monthly_surplus'])
        liquid_pool_init = round(state['liquid_pool'])
        freed_sip_init =  state['freed_timeline'][0] if state['freed_timeline']!=[] else []    #Dict[int, float],
    near_term_years = 2  
    retirement_age=state['client_data']['client_data']['retirement_age']
    user_age=state['client_data']['client_data']['client_age']
    years_to_retire=retirement_age-user_age 

    def apply_ssy_to_goal(goal, state, funded_from, current_year, end_year, ssy_tracker):
        """
        Apply SSY funds to girl child education goals.
        Should be called first in the allocation sequence for UG/PG goals.
        
        SSY Withdrawal Rules:
        - Partial withdrawal (up to 50%): Girl must be 18+ OR passed 10th grade - for higher education/marriage
        - Full withdrawal (100%): Only after 21 years from account opening (maturity)
        - Remaining 50% after partial withdrawal: LOCKED until maturity (21 years)
        
        Args:
            goal: Goal dictionary
            state: Client state
            funded_from: List to track funding sources
            current_year: Current year
            end_year: Goal target year
            ssy_tracker: Dictionary tracking SSY usage per child
        
        Returns:
            tuple: (remaining_gap, ssy_details_utilised)
           """
        # Check if this is a girl child's education goal
        child_name = goal['goal_name'].split(" ")[0]
        goal_type = goal['goal_name'].split(" ")[-1]
        goal_gap = round(goal["corpus_needed"], 0)
        
        # Get children from client data
        children = state.get('client_data', {}).get('client_data', {}).get('children', [])
        ssy_details_utilised = None

        for child in children:
            # Check if this child matches the goal name
            if child.get('child_name', '').split(" ")[0] != child_name:
                continue
                
            investments = child.get('investments', [])
            if not investments:
                continue
                
            for inv in investments:
                if inv.get('type', '').upper() != 'SUKANYA SAMRIDDHI YOJANA':
                    continue
                    
                # SSY found for this child
                try:
                    commencement_date = datetime.strptime(inv.get('commencement_date'), '%Y-%m-%d').date()
                    child_dob = datetime.strptime(child.get('child_dob'), '%Y-%m-%d').date()
                    
                    # Calculate key dates
                    maturity_year = commencement_date.year + 21  # SSY matures 21 years from opening
                    girl_turns_18_year = child_dob.year + 18
                    ssy_interest_rate = 0.082
                    
                    # Check if SSY was already used for a previous goal
                    if child_name in ssy_tracker:
                        # SSY was already partially withdrawn
                        prev_data = ssy_tracker[child_name]
                        remaining_from_prev = prev_data['remaining_balance']
                        last_year = prev_data['last_withdrawal_year']
                        
                        # If no remaining balance, skip
                        if remaining_from_prev <= 0:
                            print(f"SSY for {child_name} fully utilized in previous goals")
                            continue
                        
                        # Grow remaining balance from last withdrawal year to current goal year
                        years_to_grow = end_year - last_year
                        
                        if years_to_grow > 0:
                            grown_balance = remaining_from_prev * ((1 + ssy_interest_rate) ** years_to_grow)
                        else:
                            grown_balance = remaining_from_prev
                        
                        # CRITICAL: Remaining balance can ONLY be withdrawn at/after maturity (21 years)
                        if end_year >= maturity_year:
                            # Full maturity reached - remaining balance available
                            available_amount = grown_balance
                            withdrawal_type = 'full_maturity_remaining'
                            new_remaining = 0
                            print(f"SSY maturity reached for {child_name}. Remaining balance {round(grown_balance)} available for {goal['goal_name']}")
                        else:
                            # Goal is BEFORE maturity - CANNOT withdraw remaining balance
                            available_amount = 0
                            withdrawal_type = 'not_eligible_before_maturity'
                            new_remaining = grown_balance
                            print(f"SSY remaining balance NOT available for {goal['goal_name']} - maturity in {maturity_year}, goal in {end_year}. Remaining {round(grown_balance)} locked until maturity.")
                        
                        total_fv_at_goal = grown_balance
                        maturity_date = f"{maturity_year}-{commencement_date.month:02d}-{commencement_date.day:02d}"
                        
                    else:
                        # First withdrawal - calculate fresh SSY future value
                        ssy_result = calculate_ssy_future_value(
                            current_value=inv.get('current_value'),
                            annual_contribution=inv.get('annual_contribution'),
                            account_opening_date=commencement_date,
                            girl_child_dob=child_dob,
                            goal_target_year=end_year,
                            goal_type=goal_type,
                            ssy_interest_rate=ssy_interest_rate
                        )
                        
                        available_amount = ssy_result.get('available_amount', 0)
                        total_fv_at_goal = ssy_result.get('total_fv_at_goal', 0)
                        withdrawal_type = ssy_result.get('withdrawal_type')
                        new_remaining = ssy_result.get('remaining_balance', 0)
                        maturity_date = ssy_result.get('maturity_date')
                        
                        if available_amount > 0:
                            print(f"SSY first withdrawal for {child_name}: {withdrawal_type}, available: {round(available_amount)}, total_fv: {round(total_fv_at_goal)}")
                        else:
                            print(f"SSY not eligible for {goal['goal_name']}: {withdrawal_type}")
                    
                    # Apply SSY if available
                    if available_amount > 0 and goal_gap > 0:
                        amount_to_use = min(available_amount, goal_gap)
                        goal_gap = goal_gap - amount_to_use
                        
                        # Calculate actual remaining after this withdrawal
                        if child_name not in ssy_tracker:
                            # First withdrawal (partial_50) - remaining is the other 50%
                            actual_remaining = new_remaining
                        else:
                            # Subsequent withdrawal (at maturity) - remaining is what's left
                            actual_remaining = available_amount - amount_to_use
                        
                        funded_from.append({
                            'type': 'ssy_funds',
                            'source': f'SSY account of {child_name}',
                            'withdrawal_type': withdrawal_type,
                            'amount_used': round(amount_to_use),
                            'total_ssy_fv': round(total_fv_at_goal),
                            'remaining_ssy_balance': round(actual_remaining),
                            'maturity_date': maturity_date,
                            'maturity_year': maturity_year,
                            'locked_until_maturity': actual_remaining > 0 and end_year < maturity_year
                        })
                        
                        # Update SSY tracker for this child
                        prev_tracker = ssy_tracker.get(child_name, {})
                        ssy_tracker[child_name] = {
                            'remaining_balance': actual_remaining,
                            'last_withdrawal_year': end_year,
                            'total_withdrawn': prev_tracker.get('total_withdrawn', 0) + amount_to_use,
                            'maturity_year': maturity_year,
                            'total_fv': prev_tracker.get('total_fv') or round(total_fv_at_goal),
                            'locked': actual_remaining > 0 and end_year < maturity_year,
                        }
                        
                        ssy_details_utilised = {
                            'child_name': child_name,
                            'amount_used': round(amount_to_use),
                            'withdrawal_type': withdrawal_type,
                            'remaining_balance': round(actual_remaining),
                            'remaining_locked_until': maturity_year if actual_remaining > 0 else None
                        }

                        print(f"Applied SSY funds of {round(amount_to_use)} to goal {goal['goal_name']}. Remaining gap: {goal_gap}. SSY remaining: {round(actual_remaining)} (locked until {maturity_year})")

                except Exception as e:
                    print(f"Error processing SSY for child {child_name}: {e}")
                    continue
                
        return round(goal_gap), ssy_details_utilised




    def filtered_freed_sip_for_goal(goal, freed_sip, retirement_year):
        """
        Return only relevant freed SIPs for a goal based on retirement year.
        If the goal occurs after retirement, ignore all freed SIPs.
        """

        if goal["target_year"] > retirement_year:

           return {}
        return {year: amt for year, amt in freed_sip.items() if year < retirement_year}

    monthly_surplus = float(monthly_surplus_init) 
    liquid_pool = float(liquid_pool_init)
    freed_sip = dict(freed_sip_init)  # year -> monthly freed at that year

    current_date=datetime.today()
    current_year=current_date.year
    retirement_year=current_year+years_to_retire 
    postponed=False 
    EMI_allocation=False  
    results = [] 
    ssy_tracker = {}
    for g in updated_goals:

        goal = {
            "goal_name": g["goal_name"],
            "target_year": int(g["target_year"]),
            "target_corpus": g['target_corpus'],
            "corpus_needed": round(float(g["corpus_needed"])),
            "corpus_gap": round(float(g["corpus_needed"])),
            "funded_from": [],
            "sourced_from": g['funded_from'],
            "filter": [{'type': 'funded'}], 
            'depriorized': False,
            'note': ["100 % of the goal is achieved"]
        } 
        # currently if 90% of the goal is meet, we consider that particular goal is achieved and do not allocate further towards it. 
        if goal["corpus_gap"] <= 0.1*goal['target_corpus']:  
            results.append(goal)
            continue

        if goal['goal_name'].split(" ")[-1]=='UG':
            max_postpone = 0
        elif goal['goal_name'].split(" ")[-1]=='PG':
            max_postpone = 0
        elif goal['goal_name']=='Retirement':
            max_postpone = 2 
        else: 
            max_postpone = 10

        achieved = False 
        for postpone in range(0, max_postpone + 1):
            end_year = goal["target_year"] + postpone
            if end_year < current_year:
                # Cannot fund goals in the past
                goal["funded_from"].append({
                    "type": "in_past",
                    "note": f"End year {end_year} < current_year {current_year}"
                })
                continue
            
            gap = round(goal["corpus_needed"])
            funded_from = []
            # apply_ssy_to_goal updates ssy_tracker in place. Like the local_*
            # copies below, an attempt that does not fund the goal must not
            # use up SSY, so the tracker is restored if this attempt fails.
            ssy_tracker_before_attempt = copy.deepcopy(ssy_tracker)
            local_freed=filtered_freed_sip_for_goal(g,freed_sip,retirement_year)
            local_surplus = monthly_surplus
            local_liquid = liquid_pool
            
            # print(f' 0type of end year - current year: {type(near_term_years)}')
            short_horizon = end_year - current_year <= near_term_years

            # Order of operations 
            if short_horizon: 

                if goal['goal_name'].split(" ")[-1]=='UG':
                    print(f"UG goal_name: {goal['goal_name']}")

                    sfunded_from=copy.deepcopy(funded_from)
                    slocal_freed=copy.deepcopy(local_freed)     # work on copies; commit only if achieved
                    slocal_surplus=copy.deepcopy(local_surplus)
                    slocal_liquid=copy.deepcopy(local_liquid)

                    rap_60=gap*0.6 
                    rap_40=gap*0.4

                    # 1) Apply Lumpsumm 
                    rap, slocal_liquid = apply_lumpsum_to_goal(rap_60, slocal_liquid, current_year, end_year, sfunded_from)
                   
                    rap=rap_40+rap 
                    
                    if rap > 0.1*round(float(goal["target_corpus"])) :  
                        # 2) Apply SIP from surplus
                        rap, slocal_surplus, slocal_freed = apply_surplus_sip_to_goal(rap, slocal_surplus, current_year, end_year, sfunded_from, slocal_freed)

                    if rap > 0.1*round(float(goal["target_corpus"])):
                        # 3) Freed SIP  
                        rap, slocal_freed = apply_freed_sip_to_goal(rap, slocal_freed, current_year, end_year, sfunded_from) 
                    
                    # if rap > 0.1*round(float(goal["target_corpus"])):
                    #     rap, slocal_liquid = apply_lumpsum_to_goal(rap, slocal_liquid, current_year, end_year, sfunded_from)
                    # import
                    if rap > 0.1*round(float(goal["target_corpus"])):
                        
                        file=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'College_Fees_Scrapper', 'default_graduation_fees.pkl')
                        with open(file, 'rb') as f: 
                            graduation_details=pickle.load(f) 
                        for edu in state['client_data']['education_planning']:
                            if edu['name_of_kid'].split(" ")[0]==goal['goal_name'].split(" ")[0] and edu.get('graduation_destination')=="International":
                                print(f"Due to gap of more than 10% in education corpus, the international graduation of {edu['name_of_kid']} is deprioritized to Domestic.")
                                
                                for grad_info in graduation_details: 
                                    if grad_info['graduation_destination']=="Domestic" and grad_info['graduation_stream']==edu['graduation_stream']:
                                    
                                        edu['current_fees_of_graduation']=grad_info['current_fees_of_graduation']
                                        edu['graduation_destination']='Domestic' 
                                        goal['corpus_needed']=grad_info['current_fees_of_graduation'] - sum([i.get('amount',0) for i in goal['sourced_from']]) 
                                        print(f"corpus_needed: {goal['corpus_needed']}")
                                        goal['target_corpus']=grad_info['current_fees_of_graduation']
                                        goal['depriorized']=True
                                        gap=goal['corpus_needed']
                                        break     

                if g['goal_name'].split(" ")[-1]=='PG':

                    sfunded_from=copy.deepcopy(funded_from)
                    slocal_freed=copy.deepcopy(local_freed)     # work on copies; commit only if achieved
                    slocal_surplus=copy.deepcopy(local_surplus)
                    slocal_liquid=copy.deepcopy(local_liquid)
                    
                    rap_60=gap*0.6
                    rap_40=gap*0.4
                    # 1) Apply Lumpsumm 
                    rap, slocal_liquid = apply_lumpsum_to_goal(rap_60, slocal_liquid, current_year, end_year, sfunded_from)
                    rap=rap_40+rap
                    
                    if rap > 0.1*round(float(goal["target_corpus"])) :  
                        # 2) Apply SIP from surplus 
                        rap, slocal_surplus, slocal_freed = apply_surplus_sip_to_goal(rap, slocal_surplus, current_year, end_year, sfunded_from, slocal_freed)

                    if rap > 0.1*round(float(goal["target_corpus"])):
                        # 3) Freed SIP  
                        rap, slocal_freed = apply_freed_sip_to_goal(rap, slocal_freed, current_year, end_year, sfunded_from) 
                    
                    # import pickle 
                    if rap > 0.1*round(float(goal["target_corpus"])): 
                        print(f"target corpus: {round(float(goal["target_corpus"]))}")
                        file=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'College_Fees_Scrapper', 'default_post_graduation_fees.pkl')
                        with open(file, 'rb') as f: 
                            graduation_details=pickle.load(f) 
                        for edu in state['client_data']['education_planning']:
                            if edu['name_of_kid'].split(" ")[0]==goal['goal_name'].split(" ")[0] and edu.get('post_graduation_destination')=="International":
                                
                                print(f"Due to gap of more than 10% in graduation corpus, international post graduation of {edu['name_of_kid']} is deprioritized to Domestic.")
                                
                                for grad_info in graduation_details: 
                                    if grad_info['graduation_destination']=="Domestic" and grad_info['post_graduation_stream']==edu['post_graduation_stream']:
                                        
                                        edu['current_fees_of_post_graduation']=grad_info['current_fees_of_post_graduation']
                                        edu['post_graduation_destination']='Domestic' 
                                        goal['corpus_needed']=grad_info['current_fees_of_post_graduation']-sum([i.get('amount',0) for i in goal['sourced_from']])
                                        goal['target_corpus']=grad_info['current_fees_of_post_graduation']
                                        goal['depriorized']=True
                                        gap=goal['corpus_needed']
                                        break
                
                local_freed = dict(freed_sip)     # work on copies; commit only if achieved
                local_surplus = monthly_surplus
                local_liquid = liquid_pool

                gap_60=gap*0.6
                gap_40=gap*0.4
                gap,ssy_details = apply_ssy_to_goal(goal=goal,state=state,funded_from=funded_from,current_year=current_year,end_year=end_year,ssy_tracker=ssy_tracker)
                if ssy_details:
                        print(f"SSY details utilised for goal {goal['goal_name']}: {ssy_details}")
                # 1) Apply Lumpsumm 
                gap, local_liquid = apply_lumpsum_to_goal(gap_60, local_liquid, current_year, end_year, funded_from)
                print(f"funded_from1: {funded_from} and gap1: {gap}")
                gap=gap_40+gap 

                if gap > 0.1*round(float(goal["target_corpus"])) :  
                    # 2) Apply SIP from surplus
                    gap, local_surplus, local_freed = apply_surplus_sip_to_goal(gap, local_surplus, current_year, end_year, funded_from, local_freed)
                    print(f"funded_from2: {funded_from} and gap2: {gap}")

                if gap > 0.1*round(float(goal["target_corpus"])):
                    # 3) Freed SIP  
                    gap, local_freed = apply_freed_sip_to_goal(gap, local_freed, current_year, end_year, funded_from) 
                    print(f"funded_from3: {funded_from} and gap3: {gap}")
                    
                if gap > 0.1*round(float(goal["target_corpus"])):
                    gap, local_liquid = apply_lumpsum_to_goal(gap, local_liquid, current_year, end_year, funded_from)
                    print(f"funded_from4: {funded_from} and gap4: {gap}")

            else: 

                if goal['goal_name'].split(" ")[-1]=='UG':

                    sfunded_from=copy.deepcopy(funded_from)
                    slocal_freed=copy.deepcopy(local_freed)     # work on copies; commit only if achieved
                    slocal_surplus=copy.deepcopy(local_surplus)
                    slocal_liquid=copy.deepcopy(local_liquid)
                    rap_60=gap*0.6
                    rap_40=gap*0.4
                
                    # 1) Apply SIP from surplus
                    rap, slocal_surplus, slocal_freed = apply_surplus_sip_to_goal(rap_60, slocal_surplus, current_year, end_year, sfunded_from, slocal_freed)
                    rap=rap_40+rap
                    
                    # 2) Freed SIP 
                    if rap > 0.1*round(float(goal["target_corpus"])) :  
                        rap, slocal_freed = apply_freed_sip_to_goal(rap, slocal_freed, current_year, end_year, sfunded_from) 
                    
                    # 3) Apply Lumpsumm
                    if rap > 0.1*round(float(goal["target_corpus"])):
                        rap, slocal_liquid = apply_lumpsum_to_goal(rap, slocal_liquid, current_year, end_year, sfunded_from)
                    
                    # Apply surplus
                    # if rap > 0.1*round(float(goal["target_corpus"])):
                    #     rap, slocal_surplus, slocal_freed = apply_surplus_sip_to_goal(rap, slocal_surplus, current_year, end_year, sfunded_from, slocal_freed)
                        
                    if rap > 0.1*round(float(goal["target_corpus"])):
                        
                        file=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'College_Fees_Scrapper', 'default_graduation_fees.pkl')
                        with open(file, 'rb') as f:  
                            graduation_details=pickle.load(f) 
                        for edu in state['client_data']['education_planning']:
                            if edu['name_of_kid'].split(" ")[0]==goal['goal_name'].split(" ")[0] and edu.get('graduation_destination')=="International":
                                print(f"Due to gap of more than 10% in education corpus, the internaional graduation of {edu['name_of_kid']} is deprioritized to Domestic.")
                                
                                for grad_info in graduation_details: 
                                    if grad_info['graduation_destination']=="Domestic" and grad_info['graduation_stream']==edu['graduation_stream']:

                                        edu['current_fees_of_graduation']=grad_info['current_fees_of_graduation']
                                        edu['graduation_destination']='Domestic' 
                                        goal['corpus_needed']=grad_info['current_fees_of_graduation']-sum([i.get('amount',0) for i in goal['sourced_from']])
                                        goal['target_corpus']=grad_info['current_fees_of_graduation']
                                        goal['depriorized']=True
                                        gap=goal['corpus_needed']
                                        break

                if g['goal_name'].split(" ")[-1]=='PG':

                    sfunded_from=copy.deepcopy(funded_from)
                    slocal_freed=copy.deepcopy(local_freed)     # work on copies; commit only if achieved
                    slocal_surplus=copy.deepcopy(local_surplus)
                    slocal_liquid=copy.deepcopy(local_liquid)
                    rap_60=gap*0.6 
                    rap_40=gap*0.4

                    # 1) Apply SIP from surplus
                    rap, slocal_surplus, slocal_freed = apply_surplus_sip_to_goal(rap_60, slocal_surplus, current_year, end_year, sfunded_from, slocal_freed)
                    rap=rap_40+rap 

                    if rap > 0.1*round(float(goal["target_corpus"])) :  
                        # 2) Freed SIP  
                        rap, slocal_freed = apply_freed_sip_to_goal(rap, slocal_freed, current_year, end_year, sfunded_from)

                    if rap > 0.1*round(float(goal["target_corpus"])):
                        # 1) Apply Lumpsumm 
                        rap, slocal_liquid = apply_lumpsum_to_goal(rap, slocal_liquid, current_year, end_year, sfunded_from)
                    
                    if rap > 0.1*round(float(goal["target_corpus"])):
                        file=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'College_Fees_Scrapper', 'default_post_graduation_fees.pkl')
                        with open(file, 'rb') as f: 
                            graduation_details=pickle.load(f) 
                        for edu in state['client_data']['education_planning']:
                            if edu['name_of_kid'].split(" ")[0]==goal['goal_name'].split(" ")[0] and edu.get('post_graduation_destination')=="International":
                                
                                print(f"Due to gap of more than 10% in education gap, international post graduation of {edu['name_of_kid']} is deprioritized to Domestic.")
                                
                                for grad_info in graduation_details: 
                                    if grad_info['post_graduation_destination']=="Domestic" and grad_info['post_graduation_stream']==edu['post_graduation_stream']:
                                        
                                        edu['current_fees_of_post_graduation']=grad_info['current_fees_of_post_graduation']
                                        edu['post_graduation_destination']='Domestic'
                                        goal['corpus_needed']=grad_info['current_fees_of_post_graduation']-sum([i.get('amount',0) for i in goal['sourced_from']])
                                        print(f"corpus_needed: {goal['corpus_needed']}")
                                        goal['target_corpus']=grad_info['current_fees_of_post_graduation']
                                        goal['depriorized']=True
                                        gap=goal['corpus_needed']
                                        break 
                
                funded_from = [] 
                local_freed = dict(freed_sip)     # work on copies; commit only if achieved
                local_surplus = monthly_surplus
                local_liquid = liquid_pool

                child_name = goal['goal_name'].split(" ")[0]
                goal_type = goal['goal_name'].split(" ")[-1]

                should_check_ssy = (goal_type in ('UG', 'PG', 'Marriage'))

                # Apply SSY first for UG/PG goals (long horizon)
                if should_check_ssy:
                  gap, ssy_details = apply_ssy_to_goal(goal=goal, state=state, funded_from=funded_from, current_year=current_year, end_year=end_year,ssy_tracker=ssy_tracker)
                  if ssy_details:
                      print(f"SSY details utilised for goal {goal['goal_name']}: {ssy_details}")                
                 
                gap_40=0 if goal['goal_name']=='Retirement' else gap*0.4    # retirement goal is first attempted to be fully covered by monthly surplus.
                gap_60=gap if goal['goal_name']=='Retirement' else gap*0.6

                # 1)  Surplus SIP
                gap, local_surplus, local_freed = apply_surplus_sip_to_goal(gap_60, local_surplus, current_year, end_year, funded_from, local_freed)
                gap=gap+gap_40 

                # # 2) Freed SIP
                if gap > 0.1*round(float(goal["target_corpus"])):
                    gap, local_freed = apply_freed_sip_to_goal(gap, local_freed, current_year, end_year, funded_from)
                    
                # 3 Lumpsum
                if gap > 0.1*round(float(goal["target_corpus"])): 
                    gap, local_liquid = apply_lumpsum_to_goal(gap, local_liquid, current_year, end_year, funded_from) 
                    
                #4 Surplus 
                if gap > 0.1*round(float(goal["target_corpus"])): 
                    gap, local_surplus, local_freed = apply_surplus_sip_to_goal(gap, local_surplus, current_year, end_year, funded_from, local_freed)
                    
            if goal['goal_name'].split(" ")[-1] in ('UG', 'PG'):
                #if gap < goal['corpus_needed']: 
                    if gap<=0.1*round(goal['target_corpus']):  
                        goal['corpus_gap'] = 0 
                        if goal['depriorized']:
                            goal['note']=[f"DEPRIORITISED International education {100*round(1-abs(gap)/goal['target_corpus'])}% of {goal['goal_name'].split(" ")[0]}'s {goal['goal_name'].split(" ")[-1]} goal is achieved"]
                        goal['note']=[f" {100*round((1-abs(gap)/goal['target_corpus']),1)}% of {goal['goal_name'].split(" ")[0]}'s {goal['goal_name'].split(" ")[-1]} goal is achieved"]
                        goal['filter']=[{'type': 'funded'}]
                        monthly_surplus = local_surplus 
                        liquid_pool = local_liquid 
                        freed_sip = local_freed
                        achieved = True 
                        goal["funded_from"].extend(funded_from)
                        break
                    else :  
                        goal['corpus_gap'] = gap
                        sip, sip_start_msg = recommend_stepup_sip_for_gap(
                            gap, goal['target_year'], current_year, funded_from
                        )
                        if goal['depriorized']: 
                             goal['note']=[f"DEPRIORITISED International education Corpus gap: {gap}, {round((1-abs(gap)/goal['target_corpus']),1)*100}% still remains for {goal['goal_name'].split(" ")[0]}'s {goal['goal_name'].split(" ")[-1]} goal. You will have to start SIP of {sip} monthly {sip_start_msg} to achieve this goal."]      
                        #sip=stepup_sip_required(gap, 0.08,int((goal['target_year']- current_year)*12),0.07)
                        #if goal['depriorized']: 
                        #    goal['note']=[f"DEPRIORITISED International education Corpus gap: {gap}, {round((1-abs(gap)/goal['target_corpus']),1)*100}% still remains for {goal['goal_name'].split(" ")[0]}'s {goal['goal_name'].split(" ")[-1]} goal. You will have to start SIP of {sip} monthly from today inorder to achive this goal."]


                        goal['note'] = [f"Corpus gap: {gap}, {round((gap/goal['corpus_needed'])*100, 2)}% still remains for {goal['goal_name'].split(' ')[0]}'s {goal['goal_name'].split(' ')[-1]} goal. You will have to start SIP of {sip} at 8%, with a annual step up of 7% {sip_start_msg}  inorder to achieve goal."]
                        goal['filter']=[{'type': 'partial_funded'}] 
                        monthly_surplus = local_surplus 
                        liquid_pool = local_liquid
                        freed_sip = local_freed
                        achieved = True
                        goal["funded_from"].extend(funded_from)
                        break 
            
            elif goal['goal_name'] == 'Retirement':
                if gap<=0.1*round(goal['target_corpus']):  
                        
                        goal['corpus_gap'] = 0  
                        goal['note']=[f" {100*round(1-abs(gap)/goal['target_corpus'])}% of {goal['goal_name']} goal is achieved"]
                        goal['filter']=[{'type': 'funded'}]
                        monthly_surplus = local_surplus  
                        liquid_pool = local_liquid
                        freed_sip = local_freed
                        achieved = True 
                        goal["funded_from"].extend(funded_from)
                        break 
                elif postpone==2:    
                        goal['corpus_gap'] = gap
                        sip, sip_start_msg = recommend_stepup_sip_for_gap(
                            gap, goal['target_year'], current_year, funded_from
                        )
                        
                        goal['note'] = [f"Corpus gap: {gap}, {round((gap/goal['corpus_needed'])*100, 2)}% still remains for {goal['goal_name'].split(' ')[0]}'s {goal['goal_name'].split(' ')[-1]} goal. You will have to start SIP of {sip} at 8%, with a annual step up of 7% {sip_start_msg}  inorder to achieve goal."]
                        goal['filter']=[{'type': 'postponed'}]
                        monthly_surplus = local_surplus 
                        liquid_pool = local_liquid 
                        freed_sip = local_freed 
                        achieved = True 
                        goal["funded_from"].extend(funded_from)
                        break 

            elif gap <= round(0.1*goal['target_corpus']): 
                goal['filter']=[{'type': 'funded'}]
                # Commit local states since goal is achieved for this postponement
                goal["corpus_gap"] = 0   
                if postpone > 0:
                    # mark postponed info once
                    goal['note']= {"type": "postponed", "postponed_years": postpone, "from_year": goal["target_year"], "to_year": end_year} 
                    goal['filter']=[{'type': 'postponed'}]
                    postponed=True
                    EMI_allocation=False
                
                goal["funded_from"].extend(funded_from)

                # Update global state
                monthly_surplus = local_surplus
                liquid_pool = local_liquid
                freed_sip = local_freed
                achieved = True
                break
            # else: try next postponement year -- this attempt failed, so undo
            # any SSY withdrawal it recorded (its funded_from is discarded too).
            ssy_tracker.clear()
            ssy_tracker.update(ssy_tracker_before_attempt)
        
        # print(f"freed_sip: {freed_sip}")
        if not achieved: 
            # Keep what we could do in the last attempt (no state change), just record failure note
            goal['corpus_gap'] = gap  
            # Check if any funds have been allocated
            sip, sip_start_msg = recommend_stepup_sip_for_gap(
                gap, goal['target_year'], current_year, funded_from
            )
            goal['note'] = [f" type: unfunded , Corpus gap: {gap}, {round((gap/goal['corpus_needed'])*100, 2)}% for {goal['goal_name']} goal could not be funded due to insufficient funds. You will have to start SIP of {sip} at 8%, with a annual step up of 7% {sip_start_msg}  inorder to achieve goal"]
            goal['filter']=[{'type': 'unfunded'}]
            monthly_surplus = local_surplus 
            liquid_pool = local_liquid 
            freed_sip = local_freed  
            postponed=True
            EMI_allocation=False

        results.append(goal) 

    ESOP_GROWTH_RATE = 0.12
    ESOP_USABLE_CAP  = 0.60    
    esops_data = state['client_data'].get('investment_details', {}).get('esops', [])
    vested_esop_value = sum(e.get('vested_esops_value', 0) for e in esops_data)

    if vested_esop_value > 0:
       # Separate UG and PG education goals that still have a gap
       ug_gap_goals = [g for g in results if g['goal_name'].split(" ")[-1] == 'UG'
                        and g.get('corpus_gap', 0) > 0
                        and any(f.get('type') in ('partial_funded', 'unfunded') for f in g.get('filter', []))]
       pg_gap_goals = [g for g in results if g['goal_name'].split(" ")[-1] == 'PG'
                        and g.get('corpus_gap', 0) > 0
                        and any(f.get('type') in ('partial_funded', 'unfunded') for f in g.get('filter', []))]
       esop_remaining_usable = vested_esop_value * ESOP_USABLE_CAP  # 60% cap applied ONCE

       for goal in ug_gap_goals + pg_gap_goals:
            if esop_remaining_usable <= 0:
                break

            years_to_goal = goal['target_year'] - current_year
            if years_to_goal <= 0:
                continue

            usable_esop_fv = round(calculate_future_value(esop_remaining_usable, ESOP_GROWTH_RATE, years_to_goal))

            amount_to_apply = min(usable_esop_fv, goal['corpus_gap'])
            if amount_to_apply <= 0:
                continue

            pv_of_used = amount_to_apply / ((1 + ESOP_GROWTH_RATE) ** years_to_goal)
            goal['corpus_gap'] = round(goal['corpus_gap'] - amount_to_apply)
            goal['funded_from'].append({
                'type': 'esop_funds',
                'source': 'Vested ESOPs',
                'from_year': current_year,
                'to_year': goal['target_year'],
                'vested_value_today': round(vested_esop_value),
                'usable_esop_today': round(vested_esop_value * ESOP_USABLE_CAP),
                'usable_esop_fv_at_goal': usable_esop_fv,
                'pv_allocated_today': round(pv_of_used),
                'fv_contribution': round(amount_to_apply),
                'amount_used': round(amount_to_apply),
                'rate': f"{ESOP_GROWTH_RATE * 100:.1f}%",
                'growth_rate': ESOP_GROWTH_RATE,
                'years_to_goal': years_to_goal
            })

            esop_remaining_usable = max(0, esop_remaining_usable - pv_of_used)

            if goal['corpus_gap'] <= 0.1 * goal['target_corpus']:
                remaining_gap =goal['corpus_gap']
                goal['corpus_gap'] = 0
                child_name = goal['goal_name'].split(" ")[0]
                goal_type = goal['goal_name'].split(" ")[-1]
                pct_achieved = round((1 - abs(remaining_gap) / goal['target_corpus']) * 100, 1)
                goal['note'] = [f"{pct_achieved}% of {child_name}'s {goal_type} goal is achieved (includes ESOP funding)"]
                goal['filter'] = [{'type': 'funded'}]
            else:
                sip, _sip_start_msg = recommend_stepup_sip_for_gap(
                    goal['corpus_gap'],
                    goal['target_year'],
                    current_year,
                    goal.get('funded_from'),
                )
                child_name = goal['goal_name'].split(" ")[0]
                goal_type = goal['goal_name'].split(" ")[-1]
                goal['note'] = [f"Corpus gap after ESOP: {goal['corpus_gap']}, {round((goal['corpus_gap']/goal['corpus_needed'])*100, 2)}% still remains for {child_name}'s {goal_type} goal. SIP of {sip} at 8% with 7% annual step-up needed."]
                goal['filter'] = [{'type': 'partial_funded'}]
            
            print(f"ESOP applied {round(amount_to_apply)} to {goal['goal_name']}. Remaining usable ESOP (PV): {round(esop_remaining_usable)}")

    # ======================== RSU PORTFOLIO VALUATION & GOAL FUNDING ========================
    investment_details = state['client_data'].get('investment_details', {})
    RSU_GROWTH_RATE = get_rsu_growth_rate(investment_details)
    RSU_USABLE_CAP  = 0.60

    rsu_data = investment_details.get('rsu', [])
    rsu_portfolio = []

    if rsu_data:
        try:
            market_df = load_rsu_market_data()
        except FileNotFoundError:
            market_df = None
            print("RSU: market data Parquet not found — skipping RSU valuation. Run generate_rsu_parquet() first.")

        if market_df is not None:
            for rsu_entry in rsu_data:
                ticker = rsu_entry.get('ticker', '').upper()
                vesting_schedule = rsu_entry.get('vesting_schedule', [])
                if not ticker or not vesting_schedule:
                    continue

                ticker_row = market_df[market_df['ticker'] == ticker]
                if ticker_row.empty:
                    print(f"RSU: ticker {ticker} not found in market data — skipped")
                    continue

                price_usd  = float(ticker_row.iloc[0]['price_usd'])
                usd_to_inr = float(ticker_row.iloc[0]['usd_to_inr_rate'])
                sorted_sched = sorted(vesting_schedule, key=lambda x: int(x['year']))

                # --- Build per-tranche details with projected prices ---
                tranche_details = []
                prev_price_per_share_inr = None

                for i, tranche in enumerate(sorted_sched):
                    vest_year = int(tranche['year'])
                    no_shares = tranche['no_shares']

                    if i == 0:
                        price_per_share_inr = price_usd * usd_to_inr
                    else:
                        years_gap = vest_year - int(sorted_sched[i - 1]['year'])
                        price_per_share_inr = prev_price_per_share_inr * ((1 + RSU_GROWTH_RATE) ** years_gap)

                    tranche_value = round(price_per_share_inr * no_shares, 2)
                    tranche_details.append({
                        'year': vest_year,
                        'no_shares': no_shares,
                        'price_per_share_inr': round(price_per_share_inr, 2),
                        'tranche_value_inr': tranche_value
                    })
                    prev_price_per_share_inr = price_per_share_inr

                # Amount available today = first tranche only
                amount_available_today = tranche_details[0]['tranche_value_inr']
                total_rsu_value = round(sum(t['tranche_value_inr'] for t in tranche_details), 2)

                # ASCII-only log line (Windows cp1252 / uvicorn can choke on ₹ U+20B9)
                print(
                    f"RSU ({ticker}): total portfolio value = INR {total_rsu_value:,.2f} "
                    f"| available today = INR {amount_available_today:,.2f}"
                )

                # --- RSU usage tracker (tracks remaining usable across goals) ---
                # Keyed by goal target_year: cumulative vested value up to that year × usable cap
                rsu_used_tracker = {}   # goal_name -> amount used
                rsu_remaining_by_pool = {}  # vest_year_cutoff -> remaining usable

                def get_rsu_usable_by_year(cutoff_year):
                    """Sum of tranche values vesting on or before cutoff_year, capped at RSU_USABLE_CAP."""
                    cumulative = sum(t['tranche_value_inr'] for t in tranche_details if t['year'] <= cutoff_year)
                    return round(cumulative * RSU_USABLE_CAP, 2)

                # Shared tracker: how much usable RSU has been consumed so far across all goals
                rsu_consumed = 0.0

                # --- Apply to UG/PG goals with gaps ---
                ug_gap_goals_rsu = [g for g in results
                                    if g['goal_name'].split(" ")[-1] == 'UG'
                                    and g.get('corpus_gap', 0) > 0
                                    and any(f.get('type') in ('partial_funded', 'unfunded')
                                            for f in g.get('filter', []))]
                pg_gap_goals_rsu = [g for g in results
                                    if g['goal_name'].split(" ")[-1] == 'PG'
                                    and g.get('corpus_gap', 0) > 0
                                    and any(f.get('type') in ('partial_funded', 'unfunded')
                                            for f in g.get('filter', []))]

                for goal in ug_gap_goals_rsu + pg_gap_goals_rsu:
                    goal_year = goal['target_year']
                    years_to_goal = goal_year - current_year
                    if years_to_goal <= 0:
                        continue

                    # Usable pool = tranches vesting on or before goal year, minus what's already consumed
                    total_usable_by_goal_year = get_rsu_usable_by_year(goal_year)
                    rsu_available_for_goal = max(0, total_usable_by_goal_year - rsu_consumed)

                    if rsu_available_for_goal <= 0:
                        continue

                    amount_to_apply = min(rsu_available_for_goal, goal['corpus_gap'])
                    if amount_to_apply <= 0:
                        continue

                    draw_start = rsu_consumed
                    years_used = rsu_years_utilized_for_draw(
                        tranche_details,
                        goal_year,
                        draw_start,
                        amount_to_apply,
                        RSU_USABLE_CAP,
                    )
                    years_label = ", ".join(str(y) for y in years_used) if years_used else None

                    goal['corpus_gap'] = round(goal['corpus_gap'] - amount_to_apply)
                    rsu_consumed = round(rsu_consumed + amount_to_apply, 2)
                    rsu_used_tracker[goal['goal_name']] = round(amount_to_apply, 2)

                    goal['funded_from'].append({
                        'type': 'rsu_funds',
                        'source': f"RSU ({rsu_entry.get('company_name', ticker)})",
                        'ticker': ticker,
                        'amount_available_today': round(amount_available_today),
                        'cumulative_usable_by_goal_year': round(total_usable_by_goal_year),
                        'amount_used': round(amount_to_apply),
                        'fv_contribution': round(amount_to_apply),
                        'rsu_years_utilized': years_used,
                        'rsu_years_utilized_label': years_label,
                        'rate': f"{RSU_GROWTH_RATE * 100:.1f}%",
                        'rsu_consumed_so_far': round(rsu_consumed),
                        'years_to_goal': years_to_goal
                    })

                    if goal['corpus_gap'] <= 0.1 * goal['target_corpus']:
                        remaining_gap = goal['corpus_gap']
                        goal['corpus_gap'] = 0
                        child_name = goal['goal_name'].split(" ")[0]
                        goal_type  = goal['goal_name'].split(" ")[-1]
                        pct_achieved = min(100.0, round((1 - max(remaining_gap, 0) / goal['target_corpus']) * 100, 1))
                        goal['note']   = [f"{pct_achieved}% of {child_name}'s {goal_type} goal achieved (includes RSU funding)"]
                        goal['filter'] = [{'type': 'funded'}]
                    else:
                        sip, _sip_start_msg = recommend_stepup_sip_for_gap(
                            goal['corpus_gap'],
                            goal_year,
                            current_year,
                            goal.get('funded_from'),
                        )
                        child_name = goal['goal_name'].split(" ")[0]
                        goal_type  = goal['goal_name'].split(" ")[-1]
                        goal['note']   = [f"Corpus gap after RSU: {goal['corpus_gap']}, {round((goal['corpus_gap']/goal['corpus_needed'])*100, 2)}% still remains for {child_name}'s {goal_type} goal. SIP of {sip} at 8% with 7% step-up needed."]
                        goal['filter'] = [{'type': 'partial_funded'}]

                    print(
                        f"RSU ({ticker}) applied INR {round(amount_to_apply):,} to {goal['goal_name']}. "
                        f"Total RSU consumed: INR {round(rsu_consumed):,}"
                    )

                rsu_portfolio.append({
                    'company_name': rsu_entry.get('company_name', ticker),
                    'ticker': ticker,
                    'price_usd_today': price_usd,
                    'usd_to_inr_rate': usd_to_inr,
                    'amount_available_today': round(amount_available_today),
                    'total_rsu_value_inr': total_rsu_value,
                    'tranches': tranche_details,
                    'rsu_used_tracker': rsu_used_tracker,
                    'rsu_total_consumed': round(rsu_consumed),
                    'rsu_remaining': max(0.0, round(total_rsu_value * RSU_USABLE_CAP - rsu_consumed, 2))
                })
    key_to_remove=[]
    for freed in freed_sip:
        if freed>=retirement_year:
            key_to_remove.append(freed) 
    
    for key in key_to_remove:
        freed_sip.pop(key)

    # print(f"freed_sip afterwards: {freed_sip}")

    fund_allocation={
        "goals": results,
        "ending_monthly_surplus": monthly_surplus,
        "ending_liquid_pool": liquid_pool,
        "ending_freed_sip_schedule": freed_sip,
        "rsu_portfolio": rsu_portfolio,
        "ssy_tracker": ssy_tracker,
        # Display-only: each SSY account projected to maturity. Read by the
        # plan deck; nothing in the workflow reads it.
        "ssy_projection": project_ssy_accounts(state, ssy_tracker, results),
    }

    if state['loans_exist'] == True:
        EMI_allocation = True   # trigger prepayment whenever loans exist; plan_prepayments sources cash from multiple streams

    print(f"Goal Allocation: {fund_allocation}\n") 
    print("--------------------------"*6)
    
    return {'goal_funding': [fund_allocation], 'EMI_allocation': EMI_allocation, 'at_optimal': False } 


def _score_loan(loan: dict, client_data: dict, today: date) -> float:
    """
    Compute a dynamic priority score for a loan based on three weighted factors:

    Loan Score = (Interest Rate Weight × 0.4) + (EMI Burden × 0.3) + (Tenure Risk × 0.3)

    Interest Rate Weight:
        >12%  → 8
        9-12% → 5
        <9%   → 2

    EMI Burden (EMI / gross monthly income):
        >50%  → 5
        30-50%→ 7
        <30%  → 3

    Tenure Risk (months remaining vs months to retirement):
        Loan outlasts retirement → 10
        Otherwise → (months_remaining / months_to_retirement) × 10
    """
    client_info = client_data.get('client_data', {})
    retirement_age = float(client_info.get('retirement_age', 60))
    client_age = float(client_info.get('client_age', 35))
    monthly_salary = float(client_data.get('financial_summary', {}).get('monthly_salary', 0) or
                           client_info.get('monthly_salary', 0))
    other_income = float(client_data.get('financial_summary', {}).get('other_income(rental/interest/other)', 0) or
                         client_info.get('other_income(rental/interest/other)', 0))
    gross_monthly_income = monthly_salary + other_income

    P = float(loan.get('outstanding_balance', 0))
    rate = float(loan.get('interest_rate', 0))
    EMI = float(loan.get('emi_amount', 0))
    r = rate / 12.0

    # Interest Rate Weight
    if rate > 0.12:
        interest_weight = 8
    elif rate >= 0.09:
        interest_weight = 5
    else:
        interest_weight = 2

    # EMI Burden
    if gross_monthly_income > 0:
        emi_ratio = EMI / gross_monthly_income
    else:
        emi_ratio = 0.0
    if emi_ratio > 0.50:
        emi_burden_score = 5
    elif emi_ratio >= 0.30:
        emi_burden_score = 7
    else:
        emi_burden_score = 3

    # Tenure Risk
    months_to_retirement = max((retirement_age - client_age) * 12, 1)
    loan_months = remaining_tenure(P, r, EMI)
    if loan_months == float('inf') or loan_months == 'inf':
        tenure_risk_score = 10
    elif loan_months > months_to_retirement:
        tenure_risk_score = 10
    else:
        tenure_risk_score = round((float(loan_months) / months_to_retirement) * 10, 1)

    return round((interest_weight * 0.4) + (emi_burden_score * 0.3) + (tenure_risk_score * 0.3), 2)


from datetime import date
import copy
from pprint import pprint

def plan_prepayments(state: ClientState):
    """
    Enhanced loan prepayment planning with:
    - Guard: skip if any post-retirement goal is still unfunded
    - Hybrid strategy:
        * Lump sum -> Snowball (smallest balance first)
        * Monthly extra -> Avalanche (highest score first)
        * BUT if a loan can be fully closed via lump sum, execute it first
    - Sequential waterfall:
        * shared monthly budget
        * shared future step-ups (freed SIP / EMI) consumed only once
    - No arbitrary % caps on monthly surplus or liquid pool — use what's available after goals
    """

    print("\n" + "=" * 120)
    print("NODE: plan_prepayments")
    print("=" * 120)

    # ------------------------------------------------------------------
    # IMPORTANT: deep copy to avoid mutating original state across runs
    # ------------------------------------------------------------------
    client_data = copy.deepcopy(state['client_data'])
    liabilities = copy.deepcopy(client_data.get('liabilities', []))

    print("\n[DEBUG] Incoming liabilities:")
    for i, L in enumerate(liabilities, 1):
        print(f"  {i}. {L.get('type')} | Balance={L.get('outstanding_balance')} | "
              f"Rate={L.get('interest_rate')} | EMI={L.get('emi_amount')} | "
              f"Penalty={L.get('is_under_penalty_period', False)}")

    # Early return if no liabilities exist
    if not liabilities or len(liabilities) == 0:
        print("\n[DEBUG] No liabilities found. Skipping prepayment planning.\n")
        final_output = {
            'liability_allocation': [{
                'per_loan': [],
                'freed_timeline': {},
                'allocated_monthly_surplus': 0.0,
                'allocated_lump_sum': 0.0,
                'assumptions': {},
                'unused_monthly_surplus': state.get('monthly_surplus', 0.0)
            }],
            'freed_timeline': [{}],
            'used_monthly_surplus': [0.0],
            'used_liquid_surplus': [0.0],
            'EMI_allocated': False,
            'loan_prepayed_times': state.get('loan_prepayed_times', 0),
            'unused_monthly_surplus': [state.get('monthly_surplus', 0.0)]
        }
        pprint(final_output, sort_dicts=False)
        return final_output

    today = date.today()
    client_info = client_data.get('client_data', {})
    retirement_age = int(client_info.get('retirement_age', 60))
    client_age = int(client_info.get('client_age', 35))
    retirement_year = today.year + (retirement_age - client_age)

    print(f"\n[DEBUG] Today: {today}")
    print(f"[DEBUG] Client age: {client_age} | Retirement age: {retirement_age} | Retirement year: {retirement_year}")

    # ------------------------------------------------------------------
    # Guard: skip prepayment if any post-retirement goal is unfunded
    # ------------------------------------------------------------------
    last_goal_funding = state['goal_funding'][-1]
    post_retirement_unfunded = [
        g for g in last_goal_funding.get('goals', [])
        if g.get('target_year', 0) > retirement_year
        and g.get('goal_type', '') != 'loan_closure'
        and float(g.get('corpus_gap', 0) or g.get('corpus_needed', 0)) > 0
    ]

    if post_retirement_unfunded:
        print(f"\n[DEBUG] Skipping prepayment: {len(post_retirement_unfunded)} unfunded post-retirement goal(s) exist.")
        for g in post_retirement_unfunded:
            print(f"  - {g.get('goal_name')} | Target Year={g.get('target_year')} | Gap={g.get('corpus_gap')}")

        baseline_result = state['liability_allocation'][0] if state.get('liability_allocation') else {
            'per_loan': [], 'freed_timeline': {}, 'allocated_monthly_surplus': 0.0,
            'allocated_lump_sum': 0.0, 'assumptions': {}, 'unused_monthly_surplus': state.get('monthly_surplus', 0.0)
        }

        final_output = {
            'liability_allocation': [baseline_result],
            'freed_timeline': [baseline_result.get('freed_timeline', {})],
            'used_monthly_surplus': [0.0],
            'used_liquid_surplus': [0.0],
            'EMI_allocated': False,
            'loan_prepayed_times': state.get('loan_prepayed_times', 0),
            'unused_monthly_surplus': [state.get('monthly_surplus', 0.0)]
        }

        print("\n[DEBUG] FINAL OUTPUT (Guard Exit):")
        pprint(final_output, sort_dicts=False)
        return final_output

    # ------------------------------------------------------------------
    # Available budgets
    # ------------------------------------------------------------------
    monthly_surplus = float(last_goal_funding.get('ending_monthly_surplus', 0))
    liquid_pool = float(last_goal_funding.get('ending_liquid_pool', 0))

    freed_sip_schedule = {
        int(yr): float(v)
        for yr, v in last_goal_funding.get('ending_freed_sip_schedule', {}).items()
    }

    freed_emi_schedule = {
        int(yr): float(v)
        for yr, v in (state['freed_timeline'][0] if state.get('freed_timeline') else {}).items()
    }

    print("\n[DEBUG] Available budgets:")
    print(f"  Monthly surplus available today : {monthly_surplus:,.2f}")
    print(f"  Liquid pool available today     : {liquid_pool:,.2f}")
    print(f"  Freed SIP schedule              : {freed_sip_schedule}")
    print(f"  Freed EMI schedule              : {freed_emi_schedule}")

    # ------------------------------------------------------------------
    # Choose preferred step-up source (same as your prior flow)
    # ------------------------------------------------------------------
    _temp_eligible = [L for L in liabilities if not L.get("is_under_penalty_period", False)]
    if _temp_eligible:
        _scored = sorted(_temp_eligible, key=lambda L: _score_loan(L, client_data, today), reverse=True)
        _top = _scored[0]
        _P = float(_top['outstanding_balance'])
        _r = float(_top['interest_rate']) / 12.0
        _EMI = float(_top['emi_amount'])
        _top_months = remaining_tenure(_P, _r, _EMI)
        if _top_months == float('inf') or _top_months == 'inf':
            _loan_close_year = today.year + 50
        else:
            _loan_close_year = _add_months(today, int(_top_months)).year
    else:
        _loan_close_year = today.year + 50

    filtered_freed_sip = {yr: v for yr, v in freed_sip_schedule.items() if yr < _loan_close_year}

    if filtered_freed_sip:
        stepup_schedule = filtered_freed_sip
        cascade_source = 'freed_sip_within_loan_tenure'
    elif freed_emi_schedule:
        stepup_schedule = {yr: v for yr, v in freed_emi_schedule.items() if yr < _loan_close_year}
        cascade_source = 'freed_emi'
    else:
        stepup_schedule = {}
        cascade_source = 'none'

    current_extra_monthly = max(0.0, monthly_surplus)

    print("\n[DEBUG] Step-up selection:")
    print(f"  Top loan close year reference : {_loan_close_year}")
    print(f"  Cascade source                : {cascade_source}")
    print(f"  Step-up schedule used         : {stepup_schedule}")
    print(f"  Current extra monthly budget  : {current_extra_monthly:,.2f}")

    # ------------------------------------------------------------------
    # Score and classify eligible loans
    # ------------------------------------------------------------------
    eligible_loans = [L for L in liabilities if not L.get("is_under_penalty_period", False)]
    ineligible_loans = [L for L in liabilities if L.get("is_under_penalty_period", False)]

    for L in eligible_loans:
        L['_score'] = _score_loan(L, client_data, today)

    print("\n[DEBUG] Loan scores:")
    for L in eligible_loans:
        print(f"  {L['type']}: Score={L['_score']}")

    # Snowball order (lump sum): smallest outstanding_balance first
    loans_snowball = sorted(eligible_loans, key=lambda x: float(x['outstanding_balance']))
    # Avalanche order (monthly extra): highest loan score first
    loans_avalanche = sorted(eligible_loans, key=lambda x: x['_score'], reverse=True)

    print("\n[DEBUG] Snowball order (lump sum):")
    for i, L in enumerate(loans_snowball, 1):
        print(f"  {i}. {L['type']} | Balance={float(L['outstanding_balance']):,.2f}")

    print("\n[DEBUG] Avalanche order (monthly extra):")
    for i, L in enumerate(loans_avalanche, 1):
        print(f"  {i}. {L['type']} | Score={L['_score']}")

    # ------------------------------------------------------------------
    # Step 1: Assign lump sums (Snowball — smallest balance first)
    # ------------------------------------------------------------------
    remaining_lump = liquid_pool
    for L in loans_snowball:
        P = float(L['outstanding_balance'])
        assigned = min(remaining_lump, P)
        L['_lump_assigned'] = assigned
        remaining_lump -= assigned
        if remaining_lump <= 0:
            break

    for L in eligible_loans:
        if '_lump_assigned' not in L:
            L['_lump_assigned'] = 0.0

    print("\n[DEBUG] Lump sum allocation:")
    for L in loans_snowball:
        print(f"  {L['type']}: Lump Assigned={L.get('_lump_assigned', 0):,.2f}")
    print(f"  Remaining lump after allocation: {remaining_lump:,.2f}")

    # ------------------------------------------------------------------
    # Step 2: Sequential waterfall simulation (shared wallet)
    # ------------------------------------------------------------------
    score_map = {id(L): L.get('_score', 0.0) for L in eligible_loans}
    lump_map = {id(L): L.get('_lump_assigned', 0.0) for L in eligible_loans}

    def _months_between(start_dt: date, end_dt: date) -> int:
        """Return whole-month difference for dates produced by _add_months()."""
        return max(0, (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month))

    def _merge_schedules(*schedules):
        merged = {}
        for sched in schedules:
            for yr, amt in sched.items():
                merged[yr] = merged.get(yr, 0.0) + float(amt)
        return merged

    def amortize_without_extra(P_start, r, EMI, months):
        """
        Roll a loan forward under regular EMI only.

        Returns:
        (
            remaining_principal,
            interest_paid,
            months_elapsed,
            closed_early
        )
        """
        P = max(0.0, float(P_start))
        total_interest_paid = 0.0
        elapsed = 0

        if P <= 0:
            return 0.0, 0.0, 0, True

        while P > 0 and elapsed < max(0, int(months)):
            interest_this_month = P * r
            principal_payment = EMI - interest_this_month
            if principal_payment <= 0:
                return P, total_interest_paid, elapsed, False

            total_interest_paid += interest_this_month
            P = max(0.0, P - principal_payment)
            elapsed += 1

        return P, total_interest_paid, elapsed, P <= 0

    def simulate_prepayment_waterfall(P_start, r, EMI, lump, remaining_stepup, start_date, current_extra, loan_type="Unknown"):
        """
        Sequential loan simulation with shared monthly budget and shared step-up pool.

        Returns:
        (
            total_months,
            total_interest_paid,
            avg_monthly_extra,
            max_monthly_extra,
            close_date,
            freed_by_year_dict,
            actually_used_stepup,
            activated_stepup_years,
            leftover_stepup
        )
        """
        print("\n" + "-" * 100)
        print(f"[SIMULATION START] {loan_type}")
        print("-" * 100)
        print(f"  Start Date            : {start_date}")
        print(f"  Principal Start       : {P_start:,.2f}")
        print(f"  Lump Sum Applied      : {lump:,.2f}")
        print(f"  Principal After Lump  : {max(0.0, P_start - lump):,.2f}")
        print(f"  EMI                   : {EMI:,.2f}")
        print(f"  Monthly Rate          : {r:.6f}")
        print(f"  Waterfall Budget Start: {current_extra:,.2f}")
        print(f"  Remaining Stepups In  : {remaining_stepup}")

        P = max(0.0, P_start)

        # If fully closed by lump sum -> close immediately today
        if P <= 0:
            close_date = start_date
            freed = {close_date.year: EMI}
            print(f"  Loan closed immediately after lump sum.")
            print(f"  Freed EMI             : {EMI:,.2f}")
            return 0, 0.0, 0.0, 0.0, close_date, freed, 0.0, set(), remaining_stepup

        sorted_stepups = sorted(remaining_stepup.items())
        month = 0
        total_interest_paid = 0.0
        total_extra_paid = 0.0
        max_monthly_extra = 0.0
        current_date = start_date
        activated_stepup_years = set()

        # This budget persists for this loan's life only
        active_extra_budget = current_extra

        while P > 0 and month < 600:
            current_year = current_date.year

            # Activate only not-yet-consumed stepups
            new_sorted = []
            for yr, amt in sorted_stepups:
                if yr <= current_year:
                    active_extra_budget += amt
                    activated_stepup_years.add(yr)
                else:
                    new_sorted.append((yr, amt))
            sorted_stepups = new_sorted

            cap = max_extra_payment(P, r, EMI)
            E = min(active_extra_budget, cap)

            interest_this_month = P * r
            principal_payment = (EMI + E) - interest_this_month

            if principal_payment <= 0:
                print(f"  [BREAK] Principal payment <= 0 at month {month}")
                break

            total_interest_paid += interest_this_month
            total_extra_paid += E
            max_monthly_extra = max(max_monthly_extra, E)
            P = max(0.0, P - principal_payment)
            month += 1
            current_date = _add_months(current_date, 1)

        close_date = current_date
        avg_monthly_extra = total_extra_paid / month if month > 0 else 0.0
        freed = {close_date.year: EMI}   # only EMI is newly freed
        actually_used_stepup = sum(amt for yr, amt in remaining_stepup.items() if yr in activated_stepup_years)
        leftover_stepup = {yr: amt for yr, amt in sorted_stepups}

        print(f"  Close Date            : {close_date}")
        print(f"  Months Taken          : {month}")
        print(f"  Total Interest Paid   : {total_interest_paid:,.2f}")
        print(f"  Avg Monthly Extra     : {avg_monthly_extra:,.2f}")
        print(f"  Stepup Years Used     : {sorted(list(activated_stepup_years))}")
        print(f"  Stepup Amount Used    : {actually_used_stepup:,.2f}")
        print(f"  Remaining Stepups Out : {leftover_stepup}")
        print(f"  Freed EMI             : {EMI:,.2f}")
        print("-" * 100)

        return (
            month,
            total_interest_paid,
            avg_monthly_extra,
            max_monthly_extra,
            close_date,
            freed,
            actually_used_stepup,
            activated_stepup_years,
            leftover_stepup
        )

    # ------------------------------------------------------------------
    # Per-loan results
    # ------------------------------------------------------------------
    per_loan_results = []
    freed_aggregate = {}
    total_allocated_lump = 0.0
    freed_sip_utilized_total = 0.0
    all_activated_stepup_years = set()
    used_monthly_surplus_actual = 0.0
    background_emi_captured_ids = set()

    # Shared waterfall state
    shared_stepup_schedule = dict(stepup_schedule)
    waterfall_budget = current_extra_monthly
    waterfall_date = today

    # ------------------------------------------------------------------
    # FIXED HYBRID EXECUTION ORDER
    #   1) Loans fully closable by lump sum -> first (Snowball priority)
    #   2) Remaining eligible loans -> Avalanche
    #   3) Ineligible loans -> last
    # ------------------------------------------------------------------
    fully_closable_loans = [
        L for L in loans_snowball
        if L.get('_lump_assigned', 0.0) >= float(L['outstanding_balance'])
    ]

    remaining_loans = [
        L for L in loans_avalanche
        if L not in fully_closable_loans
    ]

    all_loans = fully_closable_loans + remaining_loans + ineligible_loans

    print("\n[DEBUG] FINAL EXECUTION ORDER (AFTER FIX):")
    for i, L in enumerate(all_loans, 1):
        print(f"  {i}. {L['type']} | "
              f"Lump={L.get('_lump_assigned', 0):,.2f} | "
              f"Balance={float(L['outstanding_balance']):,.2f} | "
              f"Score={L.get('_score')}")

    for idx, L in enumerate(all_loans):
        print("\n" + "#" * 120)
        print(f"[PROCESSING LOAN] {L['type']}")
        print("#" * 120)

        P = float(L['outstanding_balance'])
        i_annual = float(L['interest_rate'])
        EMI = float(L['emi_amount'])
        r = i_annual / 12.0
        is_eligible = not L.get('is_under_penalty_period', False)
        penalty_months = L.get('time_left_to_come_out_of_penalty_period(months)', None)

        print(f"  Balance              : {P:,.2f}")
        print(f"  Annual Rate          : {i_annual:.4f}")
        print(f"  EMI                  : {EMI:,.2f}")
        print(f"  Eligible             : {is_eligible}")
        print(f"  Waterfall Date In    : {waterfall_date}")
        print(f"  Waterfall Budget In  : {waterfall_budget:,.2f}")
        print(f"  Shared Stepups In    : {shared_stepup_schedule}")

        base_months = remaining_tenure(P, r, EMI)

        if base_months == float('inf') or base_months == 'inf':
            print("  [WARNING] Loan is non-amortizing under current EMI.")
            per_loan_results.append({
                "type": L["type"],
                "loan_score": score_map.get(id(L), 0.0) if is_eligible else None,
                "baseline_months": None,
                "baseline_close_date": None,
                "accelerated_months": None,
                "accelerated_close_date": None,
                "interest_saved": None,
                "monthly_extra_assigned": 0.0,
                "monthly_extra_applied": 0.0,
                "lump_sum_assigned": 0.0,
                "lump_sum_applied": 0.0,
                "freed_by_year": {},
                "allocation_method_monthly": "avalanche_stepup" if is_eligible else "skipped_penalty",
                "allocation_method_lump": "snowball" if is_eligible else "skipped_penalty",
                "penalty_expires_in_months": penalty_months,
                "note": "EMI <= monthly interest; loan is not amortizing at current EMI."
            })
            continue

        base_close_dt = _add_months(today, int(base_months))
        base_interest = total_interest(P, EMI, base_months)

        print(f"  Baseline Months      : {base_months:.2f}")
        print(f"  Baseline Close Date  : {base_close_dt}")
        print(f"  Baseline Interest    : {base_interest:,.2f}")

        LUMP = lump_map.get(id(L), 0.0) if is_eligible else 0.0
        loan_score = score_map.get(id(L), 0.0) if is_eligible else None
        principal_after_lump_today = max(0.0, P - LUMP)

        if is_eligible:
            incoming_stepup_schedule = dict(shared_stepup_schedule)
            loan_starts_today = waterfall_date == today
            months_until_priority = _months_between(today, waterfall_date)

            carry_balance, carry_interest, carry_months, closed_before_priority = amortize_without_extra(
                principal_after_lump_today, r, EMI, months_until_priority
            )

            print(f"  Months Until Priority : {months_until_priority}")
            print(f"  Balance At Priority   : {carry_balance:,.2f}")
            print(f"  Interest Before Extra : {carry_interest:,.2f}")

            if closed_before_priority:
                acc_months = carry_months
                acc_interest = carry_interest
                avg_extra = 0.0
                max_extra = 0.0
                acc_close_dt = _add_months(today, carry_months)
                freed = _freed_by_year(acc_close_dt, EMI)
                actually_used_stepup = 0.0
                activated_yrs = set()
                shared_stepup_schedule = incoming_stepup_schedule
                if principal_after_lump_today <= 0 and months_until_priority == 0:
                    print("  [INFO] Loan is fully closed immediately by lump sum.")
                else:
                    print("  [INFO] Loan closes naturally before it becomes the priority target.")
            else:
                background_emi_schedule = {}
                background_candidates = []
                for other in all_loans[idx + 1:]:
                    if other.get('is_under_penalty_period', False):
                        continue
                    other_id = id(other)
                    if other_id in background_emi_captured_ids:
                        continue

                    other_P = float(other['outstanding_balance'])
                    other_r = float(other['interest_rate']) / 12.0
                    other_EMI = float(other['emi_amount'])
                    other_lump = lump_map.get(other_id, 0.0)
                    other_principal_after_lump = max(0.0, other_P - other_lump)

                    if other_principal_after_lump <= 0:
                        other_close_dt = today
                    else:
                        other_natural_months = remaining_tenure(other_principal_after_lump, other_r, other_EMI)
                        if other_natural_months == float('inf') or other_natural_months == 'inf':
                            continue
                        other_close_dt = _add_months(today, int(other_natural_months))

                    if other_close_dt > waterfall_date:
                        background_emi_schedule[other_close_dt.year] = background_emi_schedule.get(other_close_dt.year, 0.0) + other_EMI
                        background_candidates.append((other_id, other_close_dt, other_EMI))

                effective_stepup_schedule = _merge_schedules(shared_stepup_schedule, background_emi_schedule)

                (
                    acc_months_after_priority,
                    acc_interest_after_priority,
                    avg_extra,
                    max_extra,
                    acc_close_dt,
                    freed,
                    actually_used_stepup,
                    activated_yrs,
                    shared_stepup_schedule
                ) = simulate_prepayment_waterfall(
                    carry_balance, r, EMI, 0.0, effective_stepup_schedule, waterfall_date, waterfall_budget, loan_type=L["type"]
                )
                acc_months = months_until_priority + acc_months_after_priority
                acc_interest = carry_interest + acc_interest_after_priority

                for other_id, other_close_dt, _ in background_candidates:
                    if other_close_dt <= acc_close_dt:
                        background_emi_captured_ids.add(other_id)

            saved_interest = base_interest - acc_interest

            # Floor to 0 if no real acceleration
            if acc_months >= int(base_months):
                print("  [INFO] No real acceleration achieved. Reverting to baseline values.")
                saved_interest = 0.0
                avg_extra = 0.0
                acc_months = int(base_months)
                acc_close_dt = base_close_dt
                freed = _freed_by_year(base_close_dt, EMI)
                max_extra = 0.0
                actually_used_stepup = 0.0
                activated_yrs = set()
                shared_stepup_schedule = incoming_stepup_schedule

            old_budget = waterfall_budget

            if principal_after_lump_today <= 0 and months_until_priority == 0:
                waterfall_budget += EMI
                waterfall_date = acc_close_dt
                background_emi_captured_ids.add(id(L))
            elif acc_months < int(base_months) and not closed_before_priority:
                # Only accelerated closures should advance the shared waterfall.
                waterfall_budget += EMI
                waterfall_date = acc_close_dt
            else:
                print("  [INFO] Shared waterfall state unchanged because this loan was not accelerated.")

            if loan_starts_today:
                used_monthly_surplus_actual = max(
                    used_monthly_surplus_actual,
                    min(current_extra_monthly, max_extra)
                )

            print(f"  Waterfall Budget Out : {old_budget:,.2f} -> {waterfall_budget:,.2f}")
            print(f"  Waterfall Date Out   : {waterfall_date}")
            print(f"  Freed SIP Used       : {actually_used_stepup:,.2f}")

            all_activated_stepup_years.update(activated_yrs)
            freed_sip_for_loan = actually_used_stepup

        else:
            # Ineligible (penalty) — show baseline only
            acc_months = int(base_months)
            acc_interest = base_interest
            saved_interest = 0.0
            avg_extra = 0.0
            freed_sip_for_loan = 0.0
            acc_close_dt = base_close_dt
            freed = _freed_by_year(base_close_dt, EMI)

            print("  [INFO] Loan skipped due to penalty period.")

        total_allocated_lump += LUMP
        freed_sip_utilized_total += freed_sip_for_loan

        for yr, amt in freed.items():
            freed_aggregate[yr] = freed_aggregate.get(yr, 0.0) + amt

        print(f"  Accelerated Months   : {acc_months}")
        print(f"  Accelerated Close Dt : {acc_close_dt}")
        print(f"  Accelerated Interest : {acc_interest:,.2f}")
        print(f"  Interest Saved       : {saved_interest:,.2f}")
        print(f"  Avg Monthly Extra    : {avg_extra:,.2f}")
        print(f"  Lump Applied         : {LUMP:,.2f}")
        print(f"  Freed By Year        : {freed}")

        per_loan_results.append({
            "type": L["type"],
            "loan_score": loan_score,
            "baseline_months": _safe(base_months),
            "baseline_close_date": base_close_dt.isoformat(),
            "accelerated_months": _safe(acc_months),
            "accelerated_close_date": acc_close_dt.isoformat(),
            "interest_saved": float(saved_interest),
            "avg_monthly_extra_applied": float(avg_extra),
            "lump_sum_applied": float(LUMP),
            "freed_by_year": {k: float(v) for k, v in freed.items()},
            "freed_sip_utilized": float(freed_sip_for_loan),
            "allocation_method_monthly": "avalanche_stepup" if is_eligible else "skipped_penalty",
            "allocation_method_lump": "snowball" if is_eligible else "skipped_penalty",
            "penalty_expires_in_months": penalty_months,
        })

    loan_prepayed_times = state['loan_prepayed_times'] + 1
    unused_monthly_surplus = max(0.0, current_extra_monthly - used_monthly_surplus_actual)

    result = {
        "per_loan": per_loan_results,
        "freed_timeline": {k: float(v) for k, v in sorted(freed_aggregate.items())},
        "allocated_monthly_surplus": float(used_monthly_surplus_actual),
        "allocated_lump_sum": float(total_allocated_lump),
        "freed_sip_utilized_total": float(freed_sip_utilized_total),
        "cascade_schedule": {
            str(yr): stepup_schedule[yr]
            for yr in sorted(all_activated_stepup_years)
            if yr in stepup_schedule
        },
        "assumptions": {
            "today": today.isoformat(),
            "monthly_budget_today": float(current_extra_monthly),
            "liquid_pool_available": float(liquid_pool),
            "stepup_source": cascade_source,
            "stepup_schedule": {str(k): v for k, v in sorted(stepup_schedule.items())},
            "monthly_strategy": "avalanche_stepup_by_loan_score",
            "lump_strategy": "snowball_by_balance",
            "simulation": "sequential_waterfall_realistic",
        },
        "unused_monthly_surplus": float(unused_monthly_surplus)
    }

    print("\n" + "=" * 120)
    print("FINAL SUMMARY")
    print("=" * 120)
    print(f"Allocated Monthly Surplus : {result['allocated_monthly_surplus']:,.2f}")
    print(f"Allocated Lump Sum        : {result['allocated_lump_sum']:,.2f}")
    print(f"Freed SIP Utilized Total  : {result['freed_sip_utilized_total']:,.2f}")
    print(f"Unused Monthly Surplus    : {result['unused_monthly_surplus']:,.2f}")
    print(f"Freed Timeline            : {result['freed_timeline']}")
    print(f"Cascade Schedule          : {result['cascade_schedule']}")

    print("\nPER LOAN SUMMARY:")
    for loan in result['per_loan']:
        print(f"  - {loan['type']}: "
              f"Baseline={loan['baseline_months']} months | "
              f"Accelerated={loan['accelerated_months']} months | "
              f"Interest Saved={loan['interest_saved']:.2f} | "
              f"Lump Applied={loan['lump_sum_applied']:.2f} | "
              f"Avg Extra={loan['avg_monthly_extra_applied']:.2f}")

    final_output = {
        'liability_allocation': [result],
        'freed_timeline': [result['freed_timeline']],
        'used_monthly_surplus': [float(used_monthly_surplus_actual)],
        'used_liquid_surplus': [float(total_allocated_lump)],
        'EMI_allocated': True,
        'loan_prepayed_times': loan_prepayed_times,
        'unused_monthly_surplus': [result['unused_monthly_surplus']]
    }

    print("\n" + "=" * 120)
    print("FINAL OUTPUT OF plan_prepayments")
    print("=" * 120)
    pprint(final_output, sort_dicts=False)
    print("=" * 120 + "\n")

    return final_output

def choose_optimal_strategy(state):
    """
    Choose optimal strategy based on goal funding and liability allocation data.
    
    Args:
        state: Dictionary containing 'goal_funding', 'liability_allocation', and 'monthly_surplus'
    
    Returns:
        Dictionary with optimal allocations and surplus information
    """
    
    # print("Node: choose_optimal_strategy \n")
    
    # Get monthly surplus from state
    print("--------------------------"*6)
    print("\n")
    print("Node: choose_optimal_strategy \n")
    print("Choosing an optimal strategy... \n")
    monthly_surplus = state.get('monthly_surplus', 0)
    
    # print(f"state['goal_funding']: {state['goal_funding']} \n")
    # print(f"state['liability_allocation']: {state['liability_allocation']} \n")
    
    # liability_allocation[0] is the baseline from freed_emi_by_year (no prepayment).
    # Real prepayment strategies start at index 1 onward.
    # goal_funding[0] is the first plan_goals run (before prepayment loop).
    # goal_funding[1], [2]... are post-prepayment reruns paired with liability_allocation[1], [2]...
    # We pair them as: (goal_funding[i+1], liability_allocation[i+1]) for i >= 0.
    prepay_loans = state['liability_allocation'][1:]   # skip baseline
    prepay_goals = state['goal_funding'][1:]           # skip pre-prepayment goal run

    # If no prepayment strategies ran, fall back to baseline
    if not prepay_loans or not prepay_goals:
        prepay_loans = state['liability_allocation']
        prepay_goals = state['goal_funding']

    # Find the first index where goals have postponed or unfunded allocations
    index_value = len(prepay_goals)  # Default to all scenarios
    for index, goals in enumerate(prepay_goals):
        has_unfunded = False
        for goal in goals['goals']:
            for allocation in goal['filter']:
                try:
                    if allocation['type'] in ['postponed', 'unfunded']:
                        index_value = index
                        has_unfunded = True
                        break
                except:
                    continue
            if has_unfunded:
                break
        if has_unfunded:
            break

    # Get feasible scenarios (all scenarios up to the first unfunded one)
    feasible_goals = prepay_goals[:index_value]
    feasible_loans = prepay_loans[:index_value]
    
    # Handle case where no feasible scenarios exist
    if not feasible_goals or not feasible_loans:
        # Use the best available: last real prepayment strategy if it exists, else baseline
        if len(prepay_loans) > 0:
            optimal_loan_alloc = prepay_loans[-1]
            optimal_goal_alloc = prepay_goals[-1] if prepay_goals else state['goal_funding'][0]
        elif len(state['liability_allocation']) > 0:
            optimal_loan_alloc = state['liability_allocation'][-1]
            optimal_goal_alloc = state['goal_funding'][0]
        else:
            optimal_loan_alloc = {
                'per_loan': [],
                'freed_timeline': {},
                'allocated_monthly_surplus': 0.0,
                'allocated_lump_sum': 0.0,
                'assumptions': {},
                'unused_monthly_surplus': state.get('monthly_surplus', 0.0)
            }
            optimal_goal_alloc = state['goal_funding'][0]

        return {
            'optimal_goal_allocation': optimal_goal_alloc,
            'optimal_loan_allocation': optimal_loan_alloc,
            'final_unused_monthly_surplus': optimal_goal_alloc['ending_monthly_surplus'],
            'at_optimal': True
        }
    
    # Ensure we have matching number of goal and loan scenarios
    min_scenarios = min(len(feasible_goals), len(feasible_loans))
    feasible_goals = feasible_goals[:min_scenarios]
    feasible_loans = feasible_loans[:min_scenarios]
    
    # Combine feasible goals and loans
    feasible_goals_loans = list(zip(feasible_goals, feasible_loans))
    
    # Calculate optimization score for each scenario using 3 signals:
    # 1. Total interest saved across all loans (normalised) — weight 0.5
    # 2. Earliest high-scored loan close date (normalised months saved) — weight 0.3
    # 3. Liquid pool preserved (normalised) — weight 0.2
    initial_liquid_pool = state.get('liquid_pool', 1.0) or 1.0

    # Find the max baseline months across all loans for normalisation
    all_baseline_months = []
    for _, loan_scenario in feasible_goals_loans:
        for loan in loan_scenario.get('per_loan', []):
            bm = loan.get('baseline_months')
            if bm and isinstance(bm, (int, float)):
                all_baseline_months.append(float(bm))
    max_baseline_months = max(all_baseline_months) if all_baseline_months else 1.0

    scenario_scores = []
    for i, (goal_scenario, loan_scenario) in enumerate(feasible_goals_loans):
        try:
            # Signal 1: Total interest saved (floored to 0, normalised by monthly_surplus * 12)
            total_interest_saved = sum(
                max(0.0, loan.get('interest_saved') or 0.0)
                for loan in loan_scenario.get('per_loan', [])
            )
            annual_surplus = monthly_surplus * 12 if monthly_surplus > 0 else 1.0
            interest_score = total_interest_saved / annual_surplus

            # Signal 2: Months saved on highest-scored loan (earlier close = better)
            per_loans = loan_scenario.get('per_loan', [])
            eligible_per_loans = [l for l in per_loans if l.get('loan_score') is not None]
            if eligible_per_loans:
                top_loan = max(eligible_per_loans, key=lambda l: l.get('loan_score') or 0)
                bm = float(top_loan.get('baseline_months') or 0)
                am = float(top_loan.get('accelerated_months') or bm)
                months_saved = max(0.0, bm - am)
            else:
                months_saved = 0.0
            acceleration_score = months_saved / max_baseline_months

            # Signal 3: Liquid pool preserved after prepayment (lower lump used = more preserved)
            lump_used = loan_scenario.get('allocated_lump_sum', 0.0)
            preserved_ratio = max(0.0, 1.0 - (lump_used / initial_liquid_pool))

            # Combined score
            combined_score = (interest_score * 0.5) + (acceleration_score * 0.3) + (preserved_ratio * 0.2)

            scenario_scores.append((i, combined_score, goal_scenario, loan_scenario))

        except (KeyError, ZeroDivisionError, TypeError):
            scenario_scores.append((i, -1, goal_scenario, loan_scenario))
    
    # Sort by combined score (highest is best)
    sorted_scenarios = sorted(scenario_scores, key=lambda x: x[1])
    
    # Get the optimal scenario (highest score)
    optimal_index, optimal_score, optimal_goal, optimal_loan = sorted_scenarios[-1]
    
    # Get unused monthly surplus from optimal scenario
    unused_monthly_surplus = optimal_goal['ending_monthly_surplus']
    
    # print(f"Selected scenario {optimal_index} with score {optimal_score}")
    # print(f"Unused monthly surplus: {unused_monthly_surplus}")
    
    print(f"Optimal Goal Strategy: {optimal_goal} \n")
    print(f"Optimal Loan Pre-payment: {optimal_loan}\n")
    print("--------------------------"*6)
    return {
        'optimal_goal_allocation': optimal_goal,
        'optimal_loan_allocation': optimal_loan,
        'final_unused_monthly_surplus': unused_monthly_surplus,
        'at_optimal': True,
        'optimization_score': optimal_score,
        'selected_scenario_index': optimal_index
    }
