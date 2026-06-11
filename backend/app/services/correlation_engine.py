import os
import json
import re
from urllib.parse import urlparse
from app.services.llm_provider import extract_json_object, generate_text, is_llm_available

def analyze_correlations(endpoints, llm_provider=None, llm_model=None):
    """
    Performs AI correlation lineage analysis:
    1. Deterministically pre-scans downstream requests for high-entropy values (JWT, cookies, sessionIDs, CSRF, auth headers).
    2. Traces upstream responses to locate where these values were generated.
    3. Calls the configured LLM to construct high-fidelity extractors and clean variable names.
    4. Automatically replaces the hardcoded values downstream with the JMeter variable expression ${c_variableName}.
    """
    if not endpoints:
        return {"endpoints": [], "correlations": []}

    correlations = infer_postman_variable_correlations(endpoints)
    
    # Track which values we've already correlated to avoid redundant work
    correlated_values = {}

    # Define simple entropy checker (length > 10, alphanumeric, typical of tokens)
    token_pattern = re.compile(r"^[a-zA-Z0-9_\-\.\=\+]{10,2048}$")
    # Matches JMeter/Postman variable expressions like ${host} or ${c_token}
    jmeter_var_pattern = re.compile(r"\$\{[^}]+\}")

    # 1. Deterministic Scan & Trace
    for i in range(len(endpoints)):
        downstream_ep = endpoints[i]

        # Scrape candidate values from headers, query params, and body
        candidates = []

        # A. Auth headers
        for h in downstream_ep.get("headers", []):
            val = h.get("value", "")
            if jmeter_var_pattern.search(val):
                continue
            if h.get("key", "").lower() == "authorization" and "bearer " in val.lower():
                token_val = val.split("Bearer ")[1].strip()
                if token_val and not jmeter_var_pattern.search(token_val):
                    candidates.append(("header", h.get("key"), token_val))
            elif h.get("key", "").lower() in ["x-csrf-token", "x-xsrf-token", "csrf-token", "xsrf-token", "cookie"]:
                # For cookie, let's try to extract specific cookie values
                if h.get("key", "").lower() == "cookie":
                    cookies = val.split(";")
                    for c in cookies:
                        if "=" in c:
                            c_name, c_val = c.split("=", 1)
                            c_name = c_name.strip()
                            c_val = c_val.strip()
                            if len(c_val) > 8 and not jmeter_var_pattern.search(c_val):
                                candidates.append(("cookie", c_name, c_val))
                else:
                    candidates.append(("header", h.get("key"), val))

        # B. Query params
        for q in downstream_ep.get("query_params", []):
            val = q.get("value", "")
            if len(val) > 8 and token_pattern.match(val) and not jmeter_var_pattern.search(val):
                candidates.append(("query", q.get("key"), val))

        # C. Body params - only scan urlencoded/formdata (not raw JSON body
        # to avoid false positives from static data fields like WSKEY, memberId)
        body_mode = downstream_ep.get("body_mode", "")
        if body_mode == "urlencoded":
            for param in downstream_ep.get("urlencoded", []):
                val = param.get("value", "")
                if len(val) > 8 and token_pattern.match(val) and not jmeter_var_pattern.search(val):
                    candidates.append(("urlencoded", param.get("key"), val))
        elif body_mode == "formdata":
            for param in downstream_ep.get("form_data", []):
                val = param.get("value", "")
                if len(val) > 8 and token_pattern.match(val) and not jmeter_var_pattern.search(val):
                    candidates.append(("formdata", param.get("key"), val))

        # Trace candidates upstream (preceding requests 0 to i-1)
        for cand_type, cand_key, cand_val in candidates:
            if cand_val in correlated_values:
                # Value already correlated, replace downstream right away
                replace_token_in_request(downstream_ep, cand_val, correlated_values[cand_val])
                continue
                
            # Scan upstream responses
            found_upstream = False
            upstream_token_endpoint_idx = None
            for j in range(i):
                upstream_ep = endpoints[j]
                
                # Check response body
                resp_body = upstream_ep.get("response_body", "")
                resp_headers = upstream_ep.get("response_headers", [])
                
                source_location = None
                response_snippet = ""
                
                # Check headers first (e.g. Set-Cookie or X-Auth-Token)
                for rh in resp_headers:
                    rh_val = rh.get("value", "")
                    if cand_val in rh_val:
                        source_location = f"header:{rh.get('key')}"
                        response_snippet = f"{rh.get('key')}: {rh_val}"
                        break
                        
                # Check body
                if not source_location and resp_body and cand_val in resp_body:
                    source_location = "body"
                    # Grab a small window around the token for the AI
                    idx = resp_body.find(cand_val)
                    start = max(0, idx - 150)
                    end = min(len(resp_body), idx + len(cand_val) + 150)
                    response_snippet = resp_body[start:end]
                    
                if source_location:
                    # Found the birth request of the token!
                    found_upstream = True
                    
                    # 2. Build an extractor. The deterministic path is first;
                    # AI is an optional precision layer when credentials exist.
                    extractor_config = generate_extractor_config(
                        upstream_url=upstream_ep.get("full_url", ""),
                        upstream_method=upstream_ep.get("method", ""),
                        upstream_mime=upstream_ep.get("response_mime_type", ""),
                        source_location=source_location,
                        snippet=response_snippet,
                        token_value=cand_val,
                        token_key=cand_key,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        test_script_info=upstream_ep.get("test_script_info", {})
                    )
                    
                    if extractor_config:
                        var_name = extractor_config["var_name"]
                        correlated_values[cand_val] = var_name
                        
                        # Check if extractor with same type and json_path/regex already exists
                        existing_extractors = upstream_ep.get("extractors", [])
                        extractor_already_exists = False
                        for existing_ext in existing_extractors:
                            if (existing_ext.get("type") == extractor_config.get("type") and
                                existing_ext.get("json_path") == extractor_config.get("json_path") and
                                existing_ext.get("regex") == extractor_config.get("regex")):
                                # Use existing extractor's var_name instead of creating duplicate
                                var_name = existing_ext["var_name"]
                                correlated_values[cand_val] = var_name
                                extractor_already_exists = True
                                break
                        
                        if not extractor_already_exists:
                            # Add extractor to the birth endpoint
                            if "extractors" not in upstream_ep:
                                upstream_ep["extractors"] = []
                            upstream_ep["extractors"].append(extractor_config)
                        
                        # Replace in this request
                        replace_token_in_request(downstream_ep, cand_val, var_name)
                        
                        correlations.append({
                            "token_name": cand_key,
                            "token_val_preview": cand_val[:12] + "...",
                            "source_index": j,
                            "source_url": upstream_ep.get("full_url", ""),
                            "target_index": i,
                            "target_url": downstream_ep.get("full_url", ""),
                            "var_name": var_name,
                            "extractor_type": extractor_config["type"]
                        })
                    break # Value correlated, move to next candidate
                
                # Track potential token endpoint (POST to /token, /oauth/token, etc.) even without response
                if upstream_token_endpoint_idx is None and is_token_endpoint(upstream_ep):
                    upstream_token_endpoint_idx = j
            
            # Fallback: Token found in downstream but not in any upstream response.
            # If there's a token endpoint upstream, create a default JSON extractor for access_token.
            if not found_upstream and upstream_token_endpoint_idx is not None:
                upstream_ep = endpoints[upstream_token_endpoint_idx]
                
                # Check if upstream endpoint has Postman test script info
                test_script_info = upstream_ep.get("test_script_info", {})
                
                # Use Postman test script info if available, otherwise use defaults
                if test_script_info and test_script_info.get("variable_name") and test_script_info.get("json_path"):
                    var_name_base = test_script_info["variable_name"]
                    json_path = test_script_info["json_path"]
                else:
                    # Assume standard OAuth response: {"access_token": "...", "token_type": "Bearer", ...}
                    var_name_base = sanitize_var_name(cand_key or 'token')
                    json_path = "$.access_token"
                
                extractor_config = {
                    "type": "json_extractor",
                    "var_name": f"c_{var_name_base}",
                    "json_path": json_path,
                    "left_boundary": None,
                    "right_boundary": None,
                    "regex": None,
                    "header_name": None
                }
                var_name = extractor_config["var_name"]
                
                # Check if extractor with same json_path already exists on this endpoint
                existing_extractors = upstream_ep.get("extractors", [])
                extractor_already_exists = False
                for existing_ext in existing_extractors:
                    if existing_ext.get("json_path") == json_path:
                        # Use existing extractor's var_name instead of creating duplicate
                        var_name = existing_ext["var_name"]
                        extractor_already_exists = True
                        break
                
                if not extractor_already_exists:
                    correlated_values[cand_val] = var_name
                    
                    if "extractors" not in upstream_ep:
                        upstream_ep["extractors"] = []
                    upstream_ep["extractors"].append(extractor_config)
                else:
                    correlated_values[cand_val] = var_name
                
                replace_token_in_request(downstream_ep, cand_val, var_name)
                
                correlations.append({
                    "token_name": cand_key,
                    "token_val_preview": cand_val[:12] + "...",
                    "source_index": upstream_token_endpoint_idx,
                    "source_url": upstream_ep.get("full_url", ""),
                    "target_index": i,
                    "target_url": downstream_ep.get("full_url", ""),
                    "var_name": var_name,
                    "extractor_type": extractor_config["type"]
                })
                    
    # Save correlation metadata to endpoints return package for visualization
    endpoints_meta = {
        "endpoints": endpoints,
        "correlations": correlations
    }
    return endpoints_meta

def infer_postman_variable_correlations(endpoints):
    correlations = []
    variable_targets = collect_jmeter_variable_targets(endpoints)

    if "token" not in variable_targets:
        return correlations

    source_index = find_token_source_endpoint(endpoints)
    if source_index is None:
        return correlations

    source_ep = endpoints[source_index]
    
    # Check if source endpoint has Postman test script info
    test_script_info = source_ep.get("test_script_info", {})
    
    # Use Postman test script info if available, otherwise use defaults
    if test_script_info and test_script_info.get("variable_name") and test_script_info.get("json_path"):
        var_name = test_script_info["variable_name"]
        json_path = test_script_info["json_path"]
    else:
        var_name = "token"
        json_path = "$.token"
    
    ensure_extractor(source_ep, {
        "type": "json_extractor",
        "var_name": var_name,
        "json_path": json_path,
        "left_boundary": None,
        "right_boundary": None,
        "regex": None,
        "header_name": None
    })
    replace_hardcoded_token_placeholders(endpoints, var_name)

    for target_index in variable_targets["token"]:
        if target_index == source_index:
            continue
        target_ep = endpoints[target_index]
        correlations.append({
            "token_name": "token",
            "token_val_preview": "${token}",
            "source_index": source_index,
            "source_url": source_ep.get("full_url", ""),
            "target_index": target_index,
            "target_url": target_ep.get("full_url", ""),
            "var_name": var_name,
            "extractor_type": "json_extractor"
        })

    return correlations

def collect_jmeter_variable_targets(endpoints):
    variable_targets = {}
    pattern = re.compile(r"\$\{([^}]+)\}")

    for idx, ep in enumerate(endpoints):
        values = []
        values.extend((h.get("value") or "") for h in ep.get("headers", []))
        values.extend((q.get("value") or "") for q in ep.get("query_params", []))
        values.append(ep.get("raw_body") or "")
        values.extend((p.get("value") or "") for p in ep.get("urlencoded", []))
        values.extend((p.get("value") or "") for p in ep.get("form_data", []))

        for value in values:
            for match in pattern.finditer(value):
                variable_targets.setdefault(match.group(1), set()).add(idx)

    return variable_targets

def is_token_endpoint(endpoint):
    """Check if an endpoint is a token/auth endpoint (POST to /token, /oauth/token, etc.)"""
    name = (endpoint.get("name") or "").lower()
    path = (endpoint.get("path") or endpoint.get("full_url") or "").lower()
    method = (endpoint.get("method") or "").upper()
    if method != "POST":
        return False
    # Common token endpoint patterns
    token_indicators = [
        "token" in path,
        "oauth" in path and "token" in path,
        "auth" in path and "token" in path,
        "login" in path,
        "signin" in path,
        "token" in name,
        "createtoken" in name.replace(" ", ""),
        "gettoken" in name.replace(" ", ""),
    ]
    return any(token_indicators)

def sanitize_var_name(name):
    """Sanitize a name for use as JMeter variable (alphanumeric only)"""
    return re.sub(r'[^a-zA-Z0-9]', '', name or "token") or "token"

def find_token_source_endpoint(endpoints):
    for idx, ep in enumerate(endpoints):
        if is_token_endpoint(ep):
            return idx
    return None

def ensure_extractor(endpoint, extractor):
    existing = endpoint.setdefault("extractors", [])
    if any(item.get("var_name") == extractor["var_name"] for item in existing):
        return
    existing.append(extractor)

def replace_hardcoded_token_placeholders(endpoints, variable_name):
    replacement = f"${{{variable_name}}}"
    for ep in endpoints:
        if ep.get("raw_body"):
            ep["raw_body"] = replace_json_string_field(ep["raw_body"], "token", replacement)
        for param in ep.get("urlencoded", []):
            if (param.get("key") or "").lower() == "token":
                param["value"] = replacement
        for param in ep.get("form_data", []):
            if (param.get("key") or "").lower() == "token":
                param["value"] = replacement

def replace_json_string_field(text, field_name, replacement):
    return re.sub(
        rf'("{re.escape(field_name)}"\s*:\s*")([^"]*)(")',
        rf'\1{replacement}\3',
        text,
        flags=re.IGNORECASE
    )

def extract_token_candidates_from_text(text, source_type):
    if not text:
        return []

    candidates = []
    token_pattern = re.compile(r"^[a-zA-Z0-9_\-\.\=\+\/]{10,2048}$")
    try:
        payload = json.loads(text)
        for key_path, value in walk_json_values(payload):
            if isinstance(value, str) and token_pattern.match(value):
                lowered_key = key_path.lower()
                if any(marker in lowered_key for marker in ["token", "session", "csrf", "xsrf", "auth", "jwt", "id"]):
                    candidates.append((source_type, key_path, value))
    except Exception:
        for key, value in re.findall(r'"([^"]*(?:token|session|csrf|xsrf|auth|jwt|id)[^"]*)"\s*:\s*"([^"]{10,2048})"', text, re.IGNORECASE):
            if token_pattern.match(value):
                candidates.append((source_type, key, value))
    return candidates

def walk_json_values(value, prefix="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            yield from walk_json_values(child, child_prefix)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json_values(child, f"{prefix}[{index}]")
    else:
        yield prefix, value

def replace_token_in_request(request, token_value, var_name):
    """
    Helper to replace hardcoded values in downstream request elements.
    """
    if not token_value:
        return

    jmeter_expr = f"${{{var_name}}}"

    # 1. URL
    if token_value in (request.get("full_url") or ""):
        request["full_url"] = replace_outside_jmeter_vars(request["full_url"], token_value, jmeter_expr)
        for field in ("protocol", "host", "port", "path"):
            value = request.get(field) or ""
            if token_value in value:
                request[field] = replace_outside_jmeter_vars(value, token_value, jmeter_expr)

        # Re-parse URL parts only when urlparse can identify a real hostname.
        # Variable hosts such as ${c_host}/booking otherwise become path-only URLs.
        parsed = urlparse(request["full_url"])
        if parsed.hostname:
            request["protocol"] = parsed.scheme or ""
            request["host"] = parsed.hostname or ""
            request["port"] = str(parsed.port or "")
            request["path"] = parsed.path or "/"
        elif not request.get("host"):
            split_variable_host_url(request)

    # 2. Headers
    for h in request.get("headers") or []:
        val = h.get("value") or ""
        if token_value in val:
            h["value"] = replace_outside_jmeter_vars(val, token_value, jmeter_expr)

    # 3. Query Params
    for q in request.get("query_params") or []:
        val = q.get("value") or ""
        if token_value in val:
            q["value"] = replace_outside_jmeter_vars(val, token_value, jmeter_expr)

    # 4. Body
    body_mode = request.get("body_mode") or ""
    if body_mode == "raw":
        raw = request.get("raw_body") or ""
        if token_value in raw:
            request["raw_body"] = replace_outside_jmeter_vars(raw, token_value, jmeter_expr)
    elif body_mode == "urlencoded":
        for param in request.get("urlencoded") or []:
            val = param.get("value") or ""
            if token_value in val:
                param["value"] = replace_outside_jmeter_vars(val, token_value, jmeter_expr)
    elif body_mode == "formdata":
        for param in request.get("form_data") or []:
            val = param.get("value") or ""
            if token_value in val:
                param["value"] = replace_outside_jmeter_vars(val, token_value, jmeter_expr)

def replace_outside_jmeter_vars(text, token_value, replacement):
    if not text or not token_value:
        return text

    pieces = re.split(r"(\$\{[^}]+\})", text)
    for idx, piece in enumerate(pieces):
        if not piece.startswith("${"):
            pieces[idx] = piece.replace(token_value, replacement)
    return "".join(pieces)

def split_variable_host_url(request):
    full_url = request.get("full_url") or ""
    if not full_url.startswith("${"):
        return

    closing = full_url.find("}")
    if closing == -1:
        return

    request["host"] = full_url[:closing + 1]
    suffix = full_url[closing + 1:] or "/"
    if suffix.startswith("?"):
        suffix = "/" + suffix
    elif not suffix.startswith("/"):
        suffix = "/" + suffix
    request["path"] = suffix

def generate_extractor_config(upstream_url, upstream_method, upstream_mime, source_location, snippet, token_value, token_key, llm_provider=None, llm_model=None, test_script_info=None):
    deterministic_config = generate_extractor_deterministically(upstream_mime, source_location, snippet, token_value, token_key, test_script_info)
    if not is_llm_available(llm_provider):
        return deterministic_config
    return generate_extractor_with_ai(
        upstream_url,
        upstream_method,
        upstream_mime,
        source_location,
        snippet,
        token_value,
        token_key,
        llm_provider,
        llm_model
    ) or deterministic_config

def generate_extractor_deterministically(upstream_mime, source_location, snippet, token_value, token_key, test_script_info=None):
    # Use Postman test script info if available for variable name and JSON path
    if test_script_info and test_script_info.get("variable_name") and test_script_info.get("json_path"):
        var_name = f"c_{test_script_info['variable_name']}"
        # For JSON responses, use the JSON path from test script
        if source_location == "body" and ("json" in upstream_mime.lower() or looks_like_json(snippet)):
            return {
                "type": "json_extractor",
                "var_name": var_name,
                "json_path": test_script_info["json_path"],
                "left_boundary": None,
                "right_boundary": None,
                "regex": None,
                "header_name": None
            }
    else:
        sanitized_key = re.sub(r'[^a-zA-Z0-9]', '', token_key or "") or "token"
        var_name = f"c_{sanitized_key[0].lower()}{sanitized_key[1:]}"

    if source_location.startswith("header:"):
        header_name = source_location.split(":", 1)[1]
        regex = build_regex_around_token(snippet, token_value)
        return {
            "type": "header_extractor",
            "var_name": var_name,
            "json_path": None,
            "left_boundary": None,
            "right_boundary": None,
            "regex": regex,
            "header_name": header_name
        }

    if "json" in upstream_mime.lower() or looks_like_json(snippet):
        json_path = find_json_path_for_value(snippet, token_value)
        if json_path:
            return {
                "type": "json_extractor",
                "var_name": var_name,
                "json_path": json_path,
                "left_boundary": None,
                "right_boundary": None,
                "regex": None,
                "header_name": None
            }

    left_b, right_b = build_boundaries(snippet, token_value)
    if left_b or right_b:
        return {
            "type": "boundary_extractor",
            "var_name": var_name,
            "json_path": None,
            "left_boundary": left_b,
            "right_boundary": right_b,
            "regex": None,
            "header_name": None
        }

    return {
        "type": "regex_extractor",
        "var_name": var_name,
        "json_path": None,
        "left_boundary": None,
        "right_boundary": None,
        "regex": build_regex_around_token(snippet, token_value),
        "header_name": None
    }

def looks_like_json(text):
    stripped = (text or "").strip()
    return stripped.startswith("{") or stripped.startswith("[")

def find_json_path_for_value(text, token_value):
    try:
        payload = json.loads(text)
    except Exception:
        match = re.search(r'(".*?%s.*?")' % re.escape(token_value), text)
        if not match:
            return None
        return None

    for key_path, value in walk_json_values(payload):
        if value == token_value:
            return key_path
    return None

def build_boundaries(snippet, token_value):
    if not snippet or token_value not in snippet:
        return "", ""
    idx = snippet.find(token_value)
    left = snippet[max(0, idx - 40):idx]
    right = snippet[idx + len(token_value):min(len(snippet), idx + len(token_value) + 40)]
    left = left.split("\n")[-1]
    right = right.split("\n")[0]
    return left, right

def build_regex_around_token(snippet, token_value):
    if snippet and token_value in snippet:
        left, right = build_boundaries(snippet, token_value)
        if left or right:
            return f"{re.escape(left)}(.+?){re.escape(right)}"
    return f"({re.escape(token_value)})"

def generate_extractor_with_ai(upstream_url, upstream_method, upstream_mime, source_location, snippet, token_value, token_key, llm_provider=None, llm_model=None):
    """
    Calls the configured LLM to build the exact Boundary, JSONPath, Regex, or Header extractor.
    """
    prompt = f"""
    You are an expert Performance Engineer. 
    A hardcoded dynamic token was captured downstream, and we have traced its origin to this response from:
    Request URL: {upstream_method} {upstream_url}
    Response Content-Type: {upstream_mime}
    Token Location: {source_location}
    Token Key/Parameter Name: {token_key}
    Actual Token Value: {token_value}

    Here is a snippet of the response text containing the token:
    ---
    {snippet}
    ---

    We need to write a JMeter Extractor component directly below this sampler to extract this token into a variable.
    
    Choose the absolute best extractor type for this format:
    1. If the mime-type is JSON (or snippet is JSON) and the token value can be addressed by a clean JSONPath, choose "json_extractor". Provide a valid "json_path" expression (e.g. $.access_token or $.data.user.id).
    2. If the mime-type is HTML or Text, and left and right boundaries are distinct, choose "boundary_extractor". Provide the exact "left_boundary" and "right_boundary" strings (do not escape them, they will be escaped in XML automatically).
    3. If a regular expression is more suitable, choose "regex_extractor" and provide the "regex" pattern (with one capturing group like `token="([^"]+)"`).
    4. If the token was found in the response headers (source_location starts with 'header:'), choose "header_extractor". Provide the "header_name" (e.g., Set-Cookie, or X-Auth-Token) and the "regex" pattern to isolate the token from the header value.

    Respond with a strictly formatted JSON object containing:
    1. "type": One of ["json_extractor", "boundary_extractor", "regex_extractor", "header_extractor"]
    2. "var_name": A clean, readable JMeter variable name prefixed with "c_" (correlation), e.g. "c_authToken", "c_csrfToken", "c_sessionId".
    3. "json_path": (string, only if type is json_extractor, else null)
    4. "left_boundary": (string, only if type is boundary_extractor, else null)
    5. "right_boundary": (string, only if type is boundary_extractor, else null)
    6. "regex": (string, only if type is regex_extractor or header_extractor, else null)
    7. "header_name": (string, only if type is header_extractor, else null)

    Return ONLY the raw JSON block. No markdown wrapper.
    """

    try:
        text = generate_text(prompt, provider=llm_provider, model=llm_model)
        config = extract_json_object(text)
        return config
    except Exception as e:
        print(f"AI Extractor Generation failed: {e}. Falling back to default extractor.")
        
        # Default fallback
        sanitized_key = re.sub(r'[^a-zA-Z0-9]', '', token_key) or "token"
        var_name = f"c_{sanitized_key}"
        
        if "json" in upstream_mime.lower():
            return {
                "type": "json_extractor",
                "var_name": var_name,
                "json_path": f"$..{token_key}" if token_key else "$..token",
                "left_boundary": None,
                "right_boundary": None,
                "regex": None,
                "header_name": None
            }
        else:
            # Create a simple boundary extractor around the value
            # We locate the token in the snippet and try to extract a 5 char prefix/suffix
            left_b = ""
            right_b = ""
            if token_value in snippet:
                idx = snippet.find(token_value)
                left_b = snippet[max(0, idx-10):idx]
                right_b = snippet[idx+len(token_value):min(len(snippet), idx+len(token_value)+10)]
            
            return {
                "type": "boundary_extractor",
                "var_name": var_name,
                "json_path": None,
                "left_boundary": left_b or '"token":"',
                "right_boundary": right_b or '"',
                "regex": None,
                "header_name": None
            }
