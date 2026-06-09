import os
import json
import re
import copy
from app.services.execution_validator import run_jmeter
from app.services.jmx_builder import build_jmx
from app.services.logical_reconstructor import reconstruct_logical_flow
from app.services.llm_provider import extract_json_object, generate_text, get_llm_config, is_llm_available

def run_self_healing_loop(test_plan, original_endpoints, output_path="output/generated_test_plan.jmx", max_retries=3, llm_provider=None, llm_model=None):
    """
    Orchestrates the dry-run simulation and self-healing loop.
    Retries up to max_retries times if errors occur.
    """
    healing_history = []
    
    for iteration in range(1, max_retries + 1):
        print(f"--- SELF-HEALING LOOP: ITERATION {iteration} ---")
        
        # 1. Build production JMX and a constrained validation JMX.
        # The dry run must never execute the user's full load duration.
        jmx_content = build_jmx(test_plan)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(jmx_content)

        validation_path = make_validation_output_path(output_path)
        validation_plan = build_validation_plan(test_plan)
        with open(validation_path, "w", encoding="utf-8") as f:
            f.write(build_jmx(validation_plan))
            
        # 2. Run JMeter dry-run against the constrained validation plan.
        run_report = run_jmeter(validation_path)

        if run_report.get("dry_run_skipped"):
            healing_history.append({
                "iteration": iteration,
                "success": False,
                "diagnosis": run_report.get("skip_reason", "JMeter dry run was skipped."),
                "action_taken": "Generated JMX and completed XML validation only. Configure JMETER_BIN to run sampler validation.",
                "failures": run_report.get("failures", [])
            })
            return {
                "success": False,
                "jmx_content": jmx_content,
                "report": run_report,
                "healing_history": healing_history,
                "iterations": iteration
            }
        
        # If successfully executed without failures, exit loop!
        if run_report["valid"]:
            print("Dry run passed successfully! 100% success rate.")
            final_jmx = build_jmx(test_plan)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(final_jmx)
            return {
                "success": True,
                "jmx_content": final_jmx,
                "report": run_report,
                "healing_history": healing_history,
                "iterations": iteration
            }
            
        print(f"Dry run encountered {len(run_report['failures'])} failures. Launching self-healing agent...")

        if not is_llm_available(llm_provider):
            config = get_llm_config(provider=llm_provider, model=llm_model)
            healing_history.append({
                "iteration": iteration,
                "success": False,
                "diagnosis": f"AI self-healing is disabled or provider '{config['provider']}' is not configured.",
                "action_taken": "Returned deterministic JMX without AI remediation.",
                "failures": run_report["failures"]
            })
            return {
                "success": False,
                "jmx_content": jmx_content,
                "report": run_report,
                "healing_history": healing_history,
                "iterations": iteration
            }
        
        # 3. Analyze failures and execute cognitive healing
        healing_action = heal_failures_with_ai(
            failures=run_report["failures"],
            original_endpoints=original_endpoints,
            test_plan=test_plan,
            iteration=iteration,
            llm_provider=llm_provider,
            llm_model=llm_model
        )
        
        if not healing_action or not healing_action.get("new_extractor") and not healing_action.get("replacements"):
            print("AI could not formulate a repair action. Aborting self-healing to prevent infinite loops.")
            healing_history.append({
                "iteration": iteration,
                "success": False,
                "diagnosis": "AI could not determine a repair action.",
                "action_taken": "Returned deterministic JMX without additional remediation.",
                "failures": run_report["failures"]
            })
            return {
                "success": False,
                "jmx_content": jmx_content,
                "report": run_report,
                "healing_history": healing_history,
                "iterations": iteration
            }
            
        # 4. Apply AI's recommended modifications to test_plan
        apply_remediation(test_plan, original_endpoints, healing_action, llm_provider=llm_provider, llm_model=llm_model)
        
        healing_history.append({
            "iteration": iteration,
            "success": True,
            "diagnosis": healing_action.get("diagnosis", ""),
            "action_taken": healing_action.get("action_taken", ""),
            "failures": run_report["failures"]
        })
        
    # If we exited loop without passing successfully, return the final state
    final_jmx = build_jmx(test_plan)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_jmx)
        
    return {
        "success": False,
        "jmx_content": final_jmx,
        "report": run_jmeter(make_validation_output_path(output_path)),
        "healing_history": healing_history,
        "iterations": max_retries
    }

def build_validation_plan(test_plan):
    validation_plan = copy.deepcopy(test_plan)
    validation_plan["thread_group"] = {
        **validation_plan.get("thread_group", {}),
        "users": 1,
        "ramp_up": 1,
        "duration": 0,
        "loops": 1,
        "scheduler": False
    }
    return validation_plan

def make_validation_output_path(output_path):
    root, ext = os.path.splitext(output_path)
    return f"{root}_dry_run{ext or '.jmx'}"

def heal_failures_with_ai(failures, original_endpoints, test_plan, iteration, llm_provider=None, llm_model=None):
    """
    Queries the configured LLM to analyze dry-run errors, trace missing tokens in response history,
    and output highly structured extractor/replacement remediation directives.
    """
    # Grab details of failed samplers in original trace to provide context
    failed_trace_details = []
    
    for fail in failures:
        sampler_name = fail["sampler_label"]
        # Find this sampler inside our original list of endpoints
        matched_ep = None
        matched_idx = -1
        
        for idx, ep in enumerate(original_endpoints):
            if ep.get("name") == sampler_name or ep.get("full_url") == fail["url"]:
                matched_ep = ep
                matched_idx = idx
                break
                
        if matched_ep:
            failed_trace_details.append({
                "index": matched_idx,
                "name": matched_ep.get("name"),
                "method": matched_ep.get("method"),
                "url": matched_ep.get("full_url"),
                "headers": matched_ep.get("headers"),
                "body_mode": matched_ep.get("body_mode"),
                "raw_body": matched_ep.get("raw_body"),
                "response_mime": matched_ep.get("response_mime_type"),
                "response_body_preview": matched_ep.get("response_body", "")[:300]
            })

    # Prepare upstream history context for the AI (limited size to prevent token blowup)
    upstream_history = []
    # Send all endpoints up to the highest failed request index
    max_failed_idx = max([d["index"] for d in failed_trace_details]) if failed_trace_details else len(original_endpoints) - 1
    
    for idx in range(min(max_failed_idx + 1, len(original_endpoints))):
        ep = original_endpoints[idx]
        upstream_history.append({
            "index": idx,
            "method": ep.get("method"),
            "url": ep.get("full_url"),
            "response_mime": ep.get("response_mime_type"),
            "response_body_preview": ep.get("response_body", "")[:300]
        })

    # Get list of already established extractors
    active_extractors = []
    for idx, ep in enumerate(original_endpoints):
        if "extractors" in ep:
            for ext in ep["extractors"]:
                active_extractors.append({
                    "upstream_index": idx,
                    "var_name": ext["var_name"],
                    "type": ext["type"]
                })

    prompt = f"""
    You are a Senior Performance Engineer and Self-Healing Automation Agent.
    We ran a dry-run iteration of our generated JMeter load test script, and it returned failures!
    Your goal is to inspect the failed samplers, review the original capture history, diagnose the root cause (e.g. a missed authentication token, bearer token, CSRF cookie, or incorrect header), and recommend precise JMX repairs.

    Dry-Run Failure Log:
    {json.dumps(failures, indent=2)}

    Details of Failed Requests from Capture:
    {json.dumps(failed_trace_details, indent=2)}

    Upstream Ingestion History (preceding and surrounding requests/responses):
    {json.dumps(upstream_history, indent=2)}

    Active Extractor Variables Already Configured:
    {json.dumps(active_extractors, indent=2)}

    Tasks:
    1. DIAGNOSE: Why did the sampler fail? (E.g., 401 Unauthorized usually means a missing JWT or Authorization header, or CSRF token mismatch).
    2. LOCATE Birth of Token: Look closely at "Upstream Ingestion History". Find which response body or header contains the token value used in the failed request's headers or body.
    3. CREATE REPAIR PLAN:
       - Suggest a new extractor under the parent sampler (the birth index) to dynamically harvest this value.
       - Tell us which downstream requests contain this hardcoded token and should be replaced with the variable expression `${{c_variableName}}`.

    Respond with a strictly formatted JSON object:
    {{
        "diagnosis": "Why it failed, identify the token value that was missing or incorrect.",
        "action_taken": "Detailed remediation action described clearly.",
        "new_extractor": {{
            "upstream_index": (integer, the index from Upstream Ingestion History where the token was generated),
            "type": "json_extractor" | "boundary_extractor" | "regex_extractor" | "header_extractor",
            "var_name": "c_tokenName" (a clean, descriptive variable name prefixed with c_),
            "json_path": "$.path.to.token" (if type is json_extractor, else null),
            "left_boundary": "left border" (if boundary_extractor, else null),
            "right_boundary": "right border" (if boundary_extractor, else null),
            "regex": "regex pattern" (if regex_extractor or header_extractor, else null),
            "header_name": "header name" (if header_extractor, else null)
        }},
        "replacements": [
            {{
                "request_index": (integer, index of request to modify),
                "token_value": "exact hardcoded token string to replace",
                "var_name": "c_tokenName" (must match the var_name of new_extractor above)
            }}
        ]
    }}

    If the failure is not related to a missing dynamic token (e.g., a missing header or minor status mismatch), you can omit "new_extractor" and provide just the diagnosis and descriptive action.
    Return ONLY the valid raw JSON object. No markdown wrappers.
    """

    try:
        if not is_llm_available(llm_provider):
            config = get_llm_config(provider=llm_provider, model=llm_model)
            raise RuntimeError(f"AI self-healing skipped because provider '{config['provider']}' is not configured.")
        text = generate_text(prompt, provider=llm_provider, model=llm_model)
        action = extract_json_object(text)
        return action
    except Exception as e:
        print(f"AI Self-Healing formulation failed: {e}")
        return None

def apply_remediation(test_plan, original_endpoints, healing_action, llm_provider=None, llm_model=None):
    """
    Applies the remediation action directly to the test plan and flow models.
    """
    new_ext = healing_action.get("new_extractor")
    replacements = healing_action.get("replacements", [])
    
    # Handle case where AI returns a list of extractors instead of a single one
    if isinstance(new_ext, list):
        new_ext = new_ext[0] if new_ext else None
    
    # 1. Add new extractor to the test plan endpoint
    if new_ext and isinstance(new_ext, dict) and new_ext.get("upstream_index") is not None:
        upstream_idx = new_ext["upstream_index"]
        if 0 <= upstream_idx < len(original_endpoints):
            target_ep = original_endpoints[upstream_idx]
            
            extractor_obj = {
                "type": new_ext["type"],
                "var_name": new_ext["var_name"],
                "json_path": new_ext.get("json_path"),
                "left_boundary": new_ext.get("left_boundary"),
                "right_boundary": new_ext.get("right_boundary"),
                "regex": new_ext.get("regex"),
                "header_name": new_ext.get("header_name")
            }
            
            if "extractors" not in target_ep:
                target_ep["extractors"] = []
                
            # Avoid duplicate extractors
            existing_names = [e["var_name"] for e in target_ep["extractors"]]
            if extractor_obj["var_name"] not in existing_names:
                target_ep["extractors"].append(extractor_obj)
                print(f"Programmatically injected {new_ext['type']} ({new_ext['var_name']}) under request index {upstream_idx}")

    # 2. Apply replacements downstream
    from app.services.correlation_engine import replace_token_in_request
    
    # Ensure replacements is a list
    if not isinstance(replacements, list):
        replacements = []
    
    for rep in replacements:
        if not isinstance(rep, dict):
            continue
        req_idx = rep.get("request_index")
        token_val = rep.get("token_value")
        var_name = rep.get("var_name")
        
        if req_idx is None or token_val is None or var_name is None:
            continue
        
        if 0 <= req_idx < len(original_endpoints):
            downstream_ep = original_endpoints[req_idx]
            replace_token_in_request(downstream_ep, token_val, var_name)
            print(f"Replaced hardcoded token in downstream request index {req_idx} with ${{{var_name}}}")

    # 3. Reconstruct logical flow using updated endpoints
    base_think_time = test_plan.get("thread_group", {}).get("think_time", 1500)
    updated_flow = reconstruct_logical_flow(
        original_endpoints,
        llm_provider=llm_provider,
        llm_model=llm_model,
        base_think_time=base_think_time
    )
    test_plan["flow"] = updated_flow
