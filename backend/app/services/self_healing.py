import os
import json
import re
import copy
from app.services.execution_validator import run_jmeter
from app.services.jmx_builder import build_jmx
from app.services.logical_reconstructor import reconstruct_logical_flow
from app.services.llm_provider import extract_json_object, generate_text, get_llm_config, is_llm_available

def run_self_healing_loop(test_plan, original_endpoints, output_path="output/generated_test_plan.jmx", max_retries=3, llm_provider=None, llm_model=None, on_log=None):
    """
    Orchestrates the dry-run simulation and self-healing loop.
    Retries up to max_retries times if errors occur.
    on_log: optional callback(log_type, message) for real-time streaming to frontend.
    """
    def emit(log_type, message):
        if on_log:
            on_log(log_type, message)
        print(message)
    
    healing_history = []
    
    for iteration in range(1, max_retries + 1):
        emit("info", f"--- SELF-HEALING LOOP: ITERATION {iteration} ---")
        
        # 1. Build production JMX and a constrained validation JMX.
        # The dry run must never execute the user's full load duration.
        emit("info", f"[Iteration {iteration}] Building JMX test plan...")
        jmx_content = build_jmx(test_plan)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(jmx_content)

        validation_path = make_validation_output_path(output_path)
        validation_plan = build_validation_plan(test_plan)
        with open(validation_path, "w", encoding="utf-8") as f:
            f.write(build_jmx(validation_plan))
            
        # 2. Run JMeter dry-run against the constrained validation plan.
        emit("info", f"[Iteration {iteration}] Running JMeter dry-run validation...")
        run_report = run_jmeter(validation_path)

        if run_report.get("dry_run_skipped"):
            entry = {
                "iteration": iteration,
                "success": False,
                "diagnosis": run_report.get("skip_reason", "JMeter dry run was skipped."),
                "action_taken": "Generated JMX and completed XML validation only. Configure JMETER_BIN to run sampler validation.",
                "failures": run_report.get("failures", [])
            }
            healing_history.append(entry)
            emit("healing", json.dumps(entry))
            return {
                "success": False,
                "jmx_content": jmx_content,
                "report": run_report,
                "healing_history": healing_history,
                "iterations": iteration
            }
        
        # If successfully executed without failures, exit loop!
        if run_report["valid"]:
            emit("success", f"[Iteration {iteration}] Dry run passed! 100% success rate.")
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
            
        emit("error", f"[Iteration {iteration}] Dry run encountered {len(run_report['failures'])} failures. Launching self-healing agent...")

        if not is_llm_available(llm_provider):
            config = get_llm_config(provider=llm_provider, model=llm_model)
            entry = {
                "iteration": iteration,
                "success": False,
                "diagnosis": f"AI self-healing is disabled or provider '{config['provider']}' is not configured.",
                "action_taken": "Returned deterministic JMX without AI remediation.",
                "failures": run_report["failures"]
            }
            healing_history.append(entry)
            emit("healing", json.dumps(entry))
            return {
                "success": False,
                "jmx_content": jmx_content,
                "report": run_report,
                "healing_history": healing_history,
                "iterations": iteration
            }
        
        # 3. Analyze failures and execute cognitive healing
        emit("info", f"[Iteration {iteration}] AI analyzing failures and formulating repair...")
        healing_action = heal_failures_with_ai(
            failures=run_report["failures"],
            original_endpoints=original_endpoints,
            test_plan=test_plan,
            iteration=iteration,
            llm_provider=llm_provider,
            llm_model=llm_model
        )
        
        if not healing_action or not isinstance(healing_action, dict) or (not healing_action.get("new_extractor") and not healing_action.get("replacements")):
            emit("warning", f"[Iteration {iteration}] AI could not formulate a repair action. Aborting self-healing.")
            entry = {
                "iteration": iteration,
                "success": False,
                "diagnosis": "AI could not determine a repair action.",
                "action_taken": "Returned deterministic JMX without additional remediation.",
                "failures": run_report["failures"]
            }
            healing_history.append(entry)
            emit("healing", json.dumps(entry))
            return {
                "success": False,
                "jmx_content": jmx_content,
                "report": run_report,
                "healing_history": healing_history,
                "iterations": iteration
            }
            
        # 4. Apply AI's recommended modifications to test_plan
        emit("info", f"[Iteration {iteration}] Applying remediation: {healing_action.get('action_taken', '')}")
        apply_remediation(test_plan, original_endpoints, healing_action, llm_provider=llm_provider, llm_model=llm_model)
        
        entry = {
            "iteration": iteration,
            "success": True,
            "diagnosis": healing_action.get("diagnosis", ""),
            "action_taken": healing_action.get("action_taken", ""),
            "failures": run_report["failures"]
        }
        healing_history.append(entry)
        emit("healing", json.dumps(entry))
        
    # If we exited loop without passing successfully, return the final state
    emit("info", f"Self-healing loop exhausted {max_retries} iterations. Building final JMX...")
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
    Your goal is to inspect the failed samplers, review the original capture history, diagnose the root cause, and recommend precise JMX repairs.

    DRY-RUN FAILURE LOG:
    {json.dumps(failures, indent=2)}

    DETAILS OF FAILED REQUESTS FROM CAPTURE:
    {json.dumps(failed_trace_details, indent=2)}

    UPSTREAM INGESTION HISTORY (preceding and surrounding requests/responses):
    {json.dumps(upstream_history, indent=2)}

    ACTIVE EXTRACTOR VARIABLES ALREADY CONFIGURED:
    {json.dumps(active_extractors, indent=2)}

    COMMON FAILURE PATTERNS AND FIXES:
    ─────────────────────────────────────
    1. **401 Unauthorized**: Missing or expired JWT/Bearer token
       → Use "new_extractor" to extract token from upstream + "replacements" to replace hardcoded values
    
    2. **415 Unsupported Media Type**: Wrong or missing Content-Type header
       → Use "content_type_fix" to set the correct Content-Type based on request body
       → Common Content-Types: "application/json", "application/x-www-form-urlencoded", "multipart/form-data", "text/xml"
    
    3. **403 Forbidden**: CSRF token mismatch or missing security header
       → Use "csrf_fix" to extract CSRF token and add it to headers
       → CSRF tokens can be found in:
         • Response body (JSON): {{"csrf_token": "...", "_csrf": "...", "csrfToken": "..."}}
         • Response body (HTML): <input type="hidden" name="_csrf" value="...">
         • Response headers: X-CSRF-Token, X-XSRF-Token, Csrf-Token
         • Cookies: XSRF-TOKEN, CSRF-TOKEN, _csrf
    
    4. **400 Bad Request**: Missing required header or parameter
       → Use "header_fix" to add missing headers
    
    5. **404 Not Found**: Incorrect URL (rare, usually a path issue)
       → Provide diagnosis only, no auto-fix possible
    
    6. **500 Internal Server Error**: Server-side issue
       → Provide diagnosis only, may need server-side investigation

    CSRF TOKEN PATTERNS:
    ─────────────────────
    Common CSRF token variable names:
    • _csrf, csrf_token, csrfToken, XSRF-TOKEN, X-CSRF-Token
    • authenticity_token (Ruby on Rails)
    • __RequestVerificationToken (ASP.NET)
    • _token (Laravel, PHP)
    
    Common CSRF token locations:
    • JSON response body: $.csrf_token, $._csrf, $.data.csrf_token
    • HTML meta tag: <meta name="csrf-token" content="...">
    • HTML form field: <input name="_csrf" value="...">
    • Response header: X-CSRF-Token, X-XSRF-Token
    • Cookie: XSRF-TOKEN, CSRF-TOKEN

    TASKS:
    ───────
    1. DIAGNOSE: Identify the exact root cause of the failure
    2. CLASSIFY: Determine the failure type (401, 415, 403, etc.)
    3. REPAIR: Choose the appropriate fix method:
       - For CSRF token issues (403): Use "csrf_fix"
       - For Content-Type issues (415): Use "content_type_fix"
       - For missing headers: Use "header_fix"
       - For dynamic tokens: Use "new_extractor" + "replacements"
       - For multiple issues: Use combination of above

    CONTENT-TYPE DETECTION RULES:
    ──────────────────────────────
    • If request body starts with "{{" or "[" → Use "application/json"
    • If request body contains "key=value&" → Use "application/x-www-form-urlencoded"
    • If request body contains "------WebKit" or "boundary=" → Use "multipart/form-data"
    • If request body starts with "<?xml" or "<" → Use "text/xml" or "application/xml"
    • If request is GET/DELETE with no body → No Content-Type needed
    • If request has binary data → Use "application/octet-stream"

    RESPOND WITH THIS EXACT JSON FORMAT:
    {{
        "diagnosis": "Detailed explanation of why the failure occurred",
        "action_taken": "Clear description of what fix was applied",
        "failure_type": "401" | "415" | "403" | "400" | "404" | "500" | "other",
        "new_extractor": {{
            "upstream_index": (integer, where token was generated),
            "type": "json_extractor" | "boundary_extractor" | "regex_extractor" | "header_extractor",
            "var_name": "c_descriptiveName",
            "json_path": "$.path.to.value" (if json_extractor),
            "left_boundary": "text" (if boundary_extractor),
            "right_boundary": "text" (if boundary_extractor),
            "regex": "pattern" (if regex/header_extractor),
            "header_name": "Header-Name" (if header_extractor)
        }},
        "replacements": [
            {{
                "request_index": (integer),
                "token_value": "exact hardcoded value to replace",
                "var_name": "c_descriptiveName"
            }}
        ],
        "header_fix": {{
            "request_index": (integer),
            "headers_to_add": [
                {{"key": "Header-Name", "value": "Header-Value (use ${{variable}} for dynamic values)"}}
            ],
            "headers_to_remove": ["Header-Name-To-Remove"]
        }},
        "content_type_fix": {{
            "request_index": (integer, index of request to fix),
            "content_type": "application/json" | "application/x-www-form-urlencoded" | "multipart/form-data" | "text/xml" | "application/xml",
            "reason": "Why this Content-Type was chosen based on request body analysis"
        }},
        "csrf_fix": {{
            "upstream_index": (integer, index of request that returns CSRF token),
            "csrf_token_location": "body" | "header" | "cookie",
            "csrf_token_path": "$.csrf_token" | "_csrf" | "X-CSRF-Token" | "XSRF-TOKEN" (path to extract token),
            "csrf_extractor": {{
                "type": "json_extractor" | "regex_extractor" | "boundary_extractor" | "header_extractor",
                "var_name": "c_csrfToken",
                "json_path": "$.csrf_token" (if json_extractor),
                "regex": "pattern" (if regex_extractor),
                "header_name": "X-CSRF-Token" (if header_extractor),
                "cookie_name": "XSRF-TOKEN" (if cookie)
            }},
            "csrf_header_to_add": {{
                "request_index": (integer, index of request to add header),
                "header_name": "X-CSRF-Token" | "X-XSRF-Token" | "_csrf",
                "header_value": "${{c_csrfToken}}"
            }}
        }}
    }}

    IMPORTANT RULES:
    ─────────────────
    • "csrf_fix" is specifically for CSRF token issues (403 Forbidden)
    • "content_type_fix" is specifically for Content-Type headers (415 errors)
    • "header_fix" is for other headers (Authorization, etc.)
    • You can use MULTIPLE fix types if needed (e.g., csrf_fix + content_type_fix)
    • For CSRF tokens, ALWAYS extract from upstream first, then add to downstream headers
    • Return ONLY the raw JSON object, no markdown or explanations
    • Return a SINGLE JSON object, NOT a JSON array like [{{...}}]
    • The response must start with {{ and end with }} directly
    """

    try:
        if not is_llm_available(llm_provider):
            config = get_llm_config(provider=llm_provider, model=llm_model)
            raise RuntimeError(f"AI self-healing skipped because provider '{config['provider']}' is not configured.")
        text = generate_text(prompt, provider=llm_provider, model=llm_model)
        action = extract_json_object(text)
        # Normalize: if LLM returned a list, unwrap to first element
        if isinstance(action, list):
            action = action[0] if action else None
        if action and not isinstance(action, dict):
            action = None
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
            existing_extractors = target_ep.setdefault("extractors", [])
            
            equivalent_var_name = None
            for ext in existing_extractors:
                if ext.get("var_name") == extractor_obj["var_name"]:
                    equivalent_var_name = ext.get("var_name")
                    break
                if ext.get("type") == "json_extractor" and extractor_obj.get("type") == "json_extractor":
                    if ext.get("json_path") and ext.get("json_path") == extractor_obj.get("json_path"):
                        equivalent_var_name = ext.get("var_name")
                        break
                if ext.get("type") == "regex_extractor" and extractor_obj.get("type") == "regex_extractor":
                    if ext.get("regex") and ext.get("regex") == extractor_obj.get("regex"):
                        equivalent_var_name = ext.get("var_name")
                        break
                if ext.get("type") == "boundary_extractor" and extractor_obj.get("type") == "boundary_extractor":
                    if ext.get("left_boundary") == extractor_obj.get("left_boundary") and ext.get("right_boundary") == extractor_obj.get("right_boundary"):
                        equivalent_var_name = ext.get("var_name")
                        break

            if equivalent_var_name:
                print(f"Equivalent extractor already exists for {extractor_obj['type']}. Reusing {equivalent_var_name} instead of {extractor_obj['var_name']}")
                # Ensure replacements use the equivalent existing var_name
                for rep in replacements:
                    if rep.get("var_name") == extractor_obj["var_name"]:
                        rep["var_name"] = equivalent_var_name
            else:
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

    # 3. Apply header fixes (add/update/remove headers)
    header_fix = healing_action.get("header_fix")
    if header_fix and isinstance(header_fix, dict):
        req_idx = header_fix.get("request_index")
        headers_to_add = header_fix.get("headers_to_add", [])
        headers_to_remove = header_fix.get("headers_to_remove", [])
        
        if req_idx is not None and 0 <= req_idx < len(original_endpoints):
            target_ep = original_endpoints[req_idx]
            
            # Ensure headers list exists
            if "headers" not in target_ep:
                target_ep["headers"] = []
            
            # Remove headers first
            for header_name in headers_to_remove:
                if isinstance(header_name, str):
                    target_ep["headers"] = [
                        h for h in target_ep["headers"]
                        if h.get("key", "").lower() != header_name.lower()
                    ]
                    print(f"Removed header '{header_name}' from request index {req_idx}")
            
            # Add/update headers
            for header in headers_to_add:
                if not isinstance(header, dict):
                    continue
                header_key = header.get("key", "")
                header_value = header.get("value", "")
                
                if not header_key:
                    continue
                
                # Check if header already exists
                header_exists = False
                for existing_header in target_ep["headers"]:
                    if existing_header.get("key", "").lower() == header_key.lower():
                        # Update existing header
                        existing_header["value"] = header_value
                        header_exists = True
                        print(f"Updated header '{header_key}' in request index {req_idx}")
                        break
                
                # Add new header if it doesn't exist
                if not header_exists:
                    target_ep["headers"].append({
                        "key": header_key,
                        "value": header_value
                    })
                    print(f"Added header '{header_key}' to request index {req_idx}")

    # 4. Apply Content-Type fixes (specifically for 415 errors)
    content_type_fix = healing_action.get("content_type_fix")
    if content_type_fix and isinstance(content_type_fix, dict):
        req_idx = content_type_fix.get("request_index")
        content_type = content_type_fix.get("content_type", "")
        reason = content_type_fix.get("reason", "")
        
        if req_idx is not None and 0 <= req_idx < len(original_endpoints) and content_type:
            target_ep = original_endpoints[req_idx]
            
            # Ensure headers list exists
            if "headers" not in target_ep:
                target_ep["headers"] = []
            
            # Check if Content-Type header already exists
            content_type_exists = False
            for existing_header in target_ep["headers"]:
                if existing_header.get("key", "").lower() == "content-type":
                    # Update existing Content-Type header
                    old_value = existing_header.get("value", "")
                    existing_header["value"] = content_type
                    content_type_exists = True
                    print(f"[CONTENT-TYPE FIX] Updated Content-Type in request index {req_idx}: '{old_value}' -> '{content_type}'")
                    if reason:
                        print(f"[CONTENT-TYPE FIX] Reason: {reason}")
                    break
            
            # Add new Content-Type header if it doesn't exist
            if not content_type_exists:
                target_ep["headers"].append({
                    "key": "Content-Type",
                    "value": content_type
                })
                print(f"[CONTENT-TYPE FIX] Added Content-Type '{content_type}' to request index {req_idx}")
                if reason:
                    print(f"[CONTENT-TYPE FIX] Reason: {reason}")
            
            # Also update body_mode if Content-Type suggests a specific format
            if content_type == "application/json" and target_ep.get("body_mode") != "raw":
                print(f"[CONTENT-TYPE FIX] Note: Request body_mode is '{target_ep.get('body_mode')}' but Content-Type is 'application/json'. Consider updating body_mode to 'raw'.")
            elif content_type == "application/x-www-form-urlencoded" and target_ep.get("body_mode") != "urlencoded":
                print(f"[CONTENT-TYPE FIX] Note: Request body_mode is '{target_ep.get('body_mode')}' but Content-Type is 'application/x-www-form-urlencoded'. Consider updating body_mode to 'urlencoded'.")

    # 5. Apply CSRF token fixes (for 403 Forbidden errors)
    csrf_fix = healing_action.get("csrf_fix")
    if csrf_fix and isinstance(csrf_fix, dict):
        upstream_idx = csrf_fix.get("upstream_index")
        csrf_extractor = csrf_fix.get("csrf_extractor", {})
        csrf_header = csrf_fix.get("csrf_header_to_add", {})
        csrf_token_location = csrf_fix.get("csrf_token_location", "body")
        csrf_token_path = csrf_fix.get("csrf_token_path", "")
        
        # Step 5a: Add CSRF extractor to upstream endpoint
        if upstream_idx is not None and 0 <= upstream_idx < len(original_endpoints) and csrf_extractor:
            upstream_ep = original_endpoints[upstream_idx]
            
            # Ensure extractors list exists
            if "extractors" not in upstream_ep:
                upstream_ep["extractors"] = []
            
            # Build extractor object based on type
            extractor_type = csrf_extractor.get("type", "json_extractor")
            var_name = csrf_extractor.get("var_name", "c_csrfToken")
            
            extractor_obj = {
                "type": extractor_type,
                "var_name": var_name,
                "json_path": csrf_extractor.get("json_path"),
                "left_boundary": csrf_extractor.get("left_boundary"),
                "right_boundary": csrf_extractor.get("right_boundary"),
                "regex": csrf_extractor.get("regex"),
                "header_name": csrf_extractor.get("header_name")
            }
            
            # Check if similar extractor already exists
            extractor_exists = False
            for existing_ext in upstream_ep["extractors"]:
                if existing_ext.get("var_name") == var_name:
                    extractor_exists = True
                    print(f"[CSRF FIX] Extractor '{var_name}' already exists on upstream index {upstream_idx}")
                    break
                if extractor_type == "json_extractor" and existing_ext.get("type") == "json_extractor":
                    if existing_ext.get("json_path") == extractor_obj.get("json_path"):
                        extractor_exists = True
                        print(f"[CSRF FIX] Similar JSON extractor found, reusing '{existing_ext.get('var_name')}'")
                        var_name = existing_ext.get("var_name")
                        break
                elif extractor_type == "regex_extractor" and existing_ext.get("type") == "regex_extractor":
                    if existing_ext.get("regex") == extractor_obj.get("regex"):
                        extractor_exists = True
                        print(f"[CSRF FIX] Similar regex extractor found, reusing '{existing_ext.get('var_name')}'")
                        var_name = existing_ext.get("var_name")
                        break
            
            if not extractor_exists:
                upstream_ep["extractors"].append(extractor_obj)
                print(f"[CSRF FIX] Added {extractor_type} extractor '{var_name}' to upstream index {upstream_idx}")
                print(f"[CSRF FIX] CSRF token location: {csrf_token_location}, path: {csrf_token_path}")
        
        # Step 5b: Add CSRF header to downstream request
        if csrf_header and isinstance(csrf_header, dict):
            downstream_idx = csrf_header.get("request_index")
            header_name = csrf_header.get("header_name", "X-CSRF-Token")
            header_value = csrf_header.get("header_value", f"${{{var_name}}}")
            
            if downstream_idx is not None and 0 <= downstream_idx < len(original_endpoints):
                downstream_ep = original_endpoints[downstream_idx]
                
                # Ensure headers list exists
                if "headers" not in downstream_ep:
                    downstream_ep["headers"] = []
                
                # Check if CSRF header already exists
                csrf_header_exists = False
                for existing_header in downstream_ep["headers"]:
                    if existing_header.get("key", "").lower() == header_name.lower():
                        # Update existing CSRF header
                        old_value = existing_header.get("value", "")
                        existing_header["value"] = header_value
                        csrf_header_exists = True
                        print(f"[CSRF FIX] Updated '{header_name}' header in downstream index {downstream_idx}: '{old_value}' -> '{header_value}'")
                        break
                
                # Add new CSRF header if it doesn't exist
                if not csrf_header_exists:
                    downstream_ep["headers"].append({
                        "key": header_name,
                        "value": header_value
                    })
                    print(f"[CSRF FIX] Added '{header_name}' header to downstream index {downstream_idx}: '{header_value}'")
        
        # Step 5c: Handle cookie-based CSRF tokens
        if csrf_token_location == "cookie" and csrf_extractor:
            cookie_name = csrf_extractor.get("cookie_name", "XSRF-TOKEN")
            print(f"[CSRF FIX] Note: CSRF token is cookie-based. Ensure Cookie Manager is configured to send '{cookie_name}' cookie.")

    # 6. Reconstruct logical flow using updated endpoints
    base_think_time = test_plan.get("thread_group", {}).get("think_time", 1500)
    updated_flow = reconstruct_logical_flow(
        original_endpoints,
        llm_provider=llm_provider,
        llm_model=llm_model,
        base_think_time=base_think_time
    )
    test_plan["flow"] = updated_flow
