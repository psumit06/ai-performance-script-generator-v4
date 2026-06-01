import os
import json
import re
from datetime import datetime
from app.services.llm_provider import extract_json_object, generate_text, get_llm_config, is_llm_available

def reconstruct_logical_flow(endpoints, llm_provider=None, llm_model=None, base_think_time=1500):
    """
    Groups requests into logical transactions using the configured LLM,
    identifies parallel resources based on start times,
    and calculates human think-times.
    """
    if not endpoints:
        return []

    base_think_time = max(0, int(base_think_time or 0))

    # 1. AI transaction grouping
    # We pass the list of URL paths and methods to Gemini and ask it to cluster them.
    compact_list = []
    for idx, ep in enumerate(endpoints):
        compact_list.append({
            "index": idx,
            "method": ep.get("method", ""),
            "url": ep.get("full_url", "")
        })

    prompt = f"""
    You are an expert Performance Architect.
    Analyze the chronological list of HTTP API endpoints below.
    Your task is to group these requests into logical "User Actions" or "Transactions" (representing click steps in a browser, like "01_Load_Homepage", "02_Login", "03_View_Cart", "04_Checkout").
    Keep requests in chronological order. Each request should belong to exactly one transaction.

    Endpoints:
    {json.dumps(compact_list, indent=2)}

    Respond with a strictly formatted JSON object containing a list called "transactions":
    Each entry must contain:
    - "name": A descriptive name, e.g. "01_Homepage", "02_SubmitLogin", "03_GetUserDetails".
    - "start_index": The starting request index (inclusive).
    - "end_index": The ending request index (inclusive).

    Ensure that the ranges are contiguous, cover all endpoints from 0 to {len(endpoints)-1}, and are ordered chronologically.

    Return ONLY the valid JSON block. No markdown wrapper.
    """

    transactions = []
    try:
        if not is_llm_available(llm_provider):
            config = get_llm_config(provider=llm_provider, model=llm_model)
            raise RuntimeError(f"AI grouping skipped because provider '{config['provider']}' is not configured.")
        text = generate_text(prompt, provider=llm_provider, model=llm_model)
        flow_data = extract_json_object(text)
        transactions = flow_data.get("transactions", [])
    except Exception as e:
        print(f"Logical flow reconstruction failed: {e}. Falling back to default grouping.")
        transactions = build_deterministic_transactions(endpoints)

    transactions = normalize_transactions(transactions, len(endpoints))

    # Validate and adjust transaction ranges to be safe
    # Ensure they exist and cover everything
    reconstructed_flow = []
    
    for tx in transactions:
        tx_name = tx.get("name", "UserStep")
        start = tx.get("start_index", 0)
        end = tx.get("end_index", 0)
        
        # Guard rails
        start = max(0, min(start, len(endpoints)-1))
        end = max(start, min(end, len(endpoints)-1))
        
        tx_requests = endpoints[start:end+1]
        
        # 2. Parallel Request Detection within this Transaction
        # Browsers load static elements (images, css, parallel ajax) at the same time.
        # We group requests starting within 150ms of each other.
        groups = []
        current_group = []
        last_time = None
        
        for ep in tx_requests:
            # Parse start time
            started_str = ep.get("startedDateTime", "")
            current_time = None
            if started_str:
                try:
                    # Strip timezone suffix to be safe with standard formats
                    clean_str = started_str.replace("Z", "")
                    if "+" in clean_str:
                        clean_str = clean_str.split("+")[0]
                    current_time = datetime.fromisoformat(clean_str)
                except Exception:
                    pass
            
            if not current_group:
                current_group.append(ep)
                last_time = current_time
            else:
                if last_time and current_time:
                    delta = abs((current_time - last_time).total_seconds() * 1000)
                    if delta <= 150: # Parallel if <= 150ms
                        current_group.append(ep)
                    else:
                        groups.append(current_group)
                        current_group = [ep]
                        last_time = current_time
                else:
                    groups.append(current_group)
                    current_group = [ep]
                    last_time = current_time
                    
        if current_group:
            groups.append(current_group)
            
        reconstructed_flow.append({
            "transaction_name": tx_name,
            "groups": groups,
            "think_time": base_think_time
        })

    # 3. Think Time Pacing calculation between transactions
    for k in range(len(reconstructed_flow) - 1):
        curr_tx = reconstructed_flow[k]
        next_tx = reconstructed_flow[k+1]
        
        # Get last request of current transaction
        last_req = curr_tx["groups"][-1][-1]
        # Get first request of next transaction
        first_req = next_tx["groups"][0][0]
        
        # Timestamps
        last_str = last_req.get("startedDateTime", "")
        first_str = first_req.get("startedDateTime", "")
        
        if last_str and first_str:
            try:
                # Strip timezones
                clean_last = last_str.replace("Z", "").split("+")[0]
                clean_first = first_str.replace("Z", "").split("+")[0]
                
                t_last = datetime.fromisoformat(clean_last)
                t_first = datetime.fromisoformat(clean_first)
                
                # Gap in ms
                gap_ms = int((t_first - t_last).total_seconds() * 1000)
                # Subtract the duration of the last request to get clean think time
                gap_ms -= last_req.get("duration", 0)
                
                if gap_ms > 300: # Threshold of 300ms for logical pacing
                    curr_tx["think_time"] = gap_ms
            except Exception:
                    curr_tx["think_time"] = base_think_time
        else:
            curr_tx["think_time"] = base_think_time
            
    return reconstructed_flow

def build_deterministic_transactions(endpoints):
    transactions = []
    start = 0
    current_hint = endpoints[0].get("transaction_hint", "")
    last_time = parse_started_time(endpoints[0].get("startedDateTime", ""))

    for idx in range(1, len(endpoints)):
        ep = endpoints[idx]
        hint = ep.get("transaction_hint", "")
        current_time = parse_started_time(ep.get("startedDateTime", ""))
        split = False

        if hint and current_hint and hint != current_hint:
            split = True
        elif last_time and current_time:
            gap_ms = (current_time - last_time).total_seconds() * 1000
            previous_duration = endpoints[idx - 1].get("duration", 0) or 0
            if gap_ms - previous_duration > 1200:
                split = True
        elif idx - start >= 5:
            split = True

        if split:
            transactions.append({
                "name": make_transaction_name(len(transactions) + 1, endpoints[start], current_hint),
                "start_index": start,
                "end_index": idx - 1
            })
            start = idx
            current_hint = hint

        if hint:
            current_hint = hint
        if current_time:
            last_time = current_time

    transactions.append({
        "name": make_transaction_name(len(transactions) + 1, endpoints[start], current_hint),
        "start_index": start,
        "end_index": len(endpoints) - 1
    })
    return transactions

def normalize_transactions(transactions, endpoint_count):
    normalized = []
    cursor = 0
    for tx in transactions:
        start = max(cursor, min(int(tx.get("start_index", cursor)), endpoint_count - 1))
        end = max(start, min(int(tx.get("end_index", start)), endpoint_count - 1))
        if start > cursor:
            normalized.append({"name": f"{len(normalized) + 1:02d}_CapturedStep", "start_index": cursor, "end_index": start - 1})
        normalized.append({"name": tx.get("name", f"{len(normalized) + 1:02d}_CapturedStep"), "start_index": start, "end_index": end})
        cursor = end + 1
        if cursor >= endpoint_count:
            break
    if cursor < endpoint_count:
        normalized.append({"name": f"{len(normalized) + 1:02d}_CapturedStep", "start_index": cursor, "end_index": endpoint_count - 1})
    return normalized

def make_transaction_name(number, endpoint, hint):
    if hint:
        base = hint.split("/")[-1].strip()
    else:
        path = endpoint.get("path") or endpoint.get("full_url") or "CapturedStep"
        base = re.sub(r"[^a-zA-Z0-9]+", "_", path.strip("/"))[:36] or "CapturedStep"
    return f"{number:02d}_{base}"

def parse_started_time(started_str):
    if not started_str:
        return None
    try:
        clean_str = started_str.replace("Z", "")
        if "+" in clean_str:
            clean_str = clean_str.split("+")[0]
        return datetime.fromisoformat(clean_str)
    except Exception:
        return None
