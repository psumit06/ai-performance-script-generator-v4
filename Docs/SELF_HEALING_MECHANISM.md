# Self-Healing Mechanism in AI Performance Script Generator

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [How It Works](#how-it-works)
4. [Current Capabilities](#current-capabilities)
5. [AI Integration](#ai-integration)
6. [Header Injection Feature](#header-injection-feature)
7. [Configuration Options](#configuration-options)
8. [Use Cases and Examples](#use-cases-and-examples)
9. [Limitations](#limitations)
10. [Future Enhancements](#future-enhancements)

---

## Overview

The Self-Healing Mechanism is an intelligent, automated error detection and remediation system that validates generated JMeter test scripts by running dry-run executions, diagnosing failures, and automatically fixing issues without manual intervention.

### Key Benefits

- **Automated Error Detection**: Identifies failures during dry-run validation
- **Intelligent Diagnosis**: Uses AI to analyze root causes of failures
- **Automatic Remediation**: Applies fixes to extractors, headers, and token replacements
- **Iterative Improvement**: Retries up to 3 times until success
- **Deterministic Fallback**: Works even without AI configured

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SELF-HEALING LOOP (Max 3 iterations)                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  Build JMX   │───▶│  Dry-Run     │───▶│  Analyze     │                  │
│  │  (Validation)│    │  JMeter      │    │  Failures    │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│         │                   │                   │                           │
│         │                   │                   │                           │
│         ▼                   ▼                   ▼                           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  Write to    │    │  Parse JTL   │    │  AI Diagnosis│                  │
│  │  Disk        │    │  Results     │    │  + Fix       │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│                                                │                           │
│                                                │                           │
│                                                ▼                           │
│                                         ┌──────────────┐                   │
│                                         │  Apply Fix   │                   │
│                                         │  + Retry     │                   │
│                                         └──────────────┘                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | File | Purpose |
|-----------|------|---------|
| **Self-Healing Orchestrator** | `self_healing.py` | Main loop, AI diagnosis, remediation |
| **Execution Validator** | `execution_validator.py` | Runs JMeter dry-run, parses JTL results |
| **JMX Builder** | `jmx_builder.py` | Builds JMX XML with extractors |
| **Correlation Engine** | `correlation_engine.py` | Token correlation, extractor generation |
| **LLM Provider** | `llm_provider.py` | AI provider abstraction |

---

## How It Works

### Step 1: Build Validation JMX

The system creates a constrained version of the JMX file for dry-run validation:

```python
def build_validation_plan(test_plan):
    """Creates a constrained version for dry-run (1 user, 1 iteration, 10s)"""
    validation_plan = copy.deepcopy(test_plan)
    validation_plan["thread_group"] = {
        "users": 1,           # Only 1 user
        "ramp_up": 1,         # 1 second ramp-up
        "duration": 0,        # No duration limit
        "loops": 1,           # Single iteration
        "scheduler": False    # No scheduler
    }
    return validation_plan
```

**Why:** Avoid running full load test during validation (would take too long)

### Step 2: Execute Dry-Run

The system executes JMeter in headless mode with the validation JMX:

```python
def run_jmeter(jmx_path):
    # 1. Validate XML structure first
    xml_report = validate_jmx_xml(jmx_path)
    
    # 2. Check if JMeter is installed
    if not os.path.exists(jmeter_path):
        return {"dry_run_skipped": True, "skip_reason": "JMeter not found"}
    
    # 3. Run JMeter in headless mode
    result = subprocess.run(
        [jmeter_path, "-n", "-t", jmx_path, "-l", jtl_path, "-j", log_path],
        capture_output=True,
        text=True,
        timeout=120  # 2 minute timeout
    )
    
    # 4. Parse JTL results
    failures = []
    with open(jtl_path, mode="r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not is_success or resp_code.startswith("4") or resp_code.startswith("5"):
                failures.append({...})
    
    return {"valid": len(failures) == 0, "failures": failures}
```

### Step 3: AI Diagnosis

When failures occur, the system queries the configured LLM to diagnose the root cause:

```python
def heal_failures_with_ai(failures, original_endpoints, test_plan, iteration):
    # 1. Gather context about failures
    failed_trace_details = []
    for fail in failures:
        matched_ep = find_endpoint_by_name_or_url(fail["sampler_label"], fail["url"])
        failed_trace_details.append({
            "index": matched_idx,
            "name": matched_ep.get("name"),
            "url": matched_ep.get("full_url"),
            "headers": matched_ep.get("headers"),
            "body_mode": matched_ep.get("body_mode"),
            "raw_body": matched_ep.get("raw_body"),
            "response_body_preview": matched_ep.get("response_body", "")[:300]
        })
    
    # 2. Prepare upstream history
    upstream_history = []
    for idx in range(max_failed_idx + 1):
        upstream_history.append({
            "index": idx,
            "method": original_endpoints[idx].get("method"),
            "url": original_endpoints[idx].get("full_url"),
            "response_body_preview": original_endpoints[idx].get("response_body", "")[:300]
        })
    
    # 3. Send to AI for diagnosis
    prompt = f"""
    You are a Senior Performance Engineer and Self-Healing Automation Agent.
    
    Dry-Run Failure Log: {json.dumps(failures, indent=2)}
    Failed Requests Details: {json.dumps(failed_trace_details, indent=2)}
    Upstream History: {json.dumps(upstream_history, indent=2)}
    
    Tasks:
    1. DIAGNOSE: Why did the sampler fail?
    2. LOCATE Birth of Token: Find which response contains the token
    3. CREATE REPAIR PLAN: Suggest extractor, replacements, and/or header fixes
    """
    
    text = generate_text(prompt, provider=llm_provider, model=llm_model)
    action = extract_json_object(text)
    return action
```

### Step 4: Apply Remediation

The system applies the AI-recommended fixes to the test plan:

```python
def apply_remediation(test_plan, original_endpoints, healing_action):
    # 1. Add new extractor to upstream endpoint
    if new_ext and new_ext.get("upstream_index") is not None:
        upstream_idx = new_ext["upstream_index"]
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
        
        target_ep.setdefault("extractors", []).append(extractor_obj)
    
    # 2. Replace hardcoded tokens in downstream requests
    for rep in replacements:
        req_idx = rep.get("request_index")
        token_val = rep.get("token_value")
        var_name = rep.get("var_name")
        
        if req_idx is not None and token_val and var_name:
            downstream_ep = original_endpoints[req_idx]
            replace_token_in_request(downstream_ep, token_val, var_name)
    
    # 3. Apply header fixes (add/update/remove headers)
    header_fix = healing_action.get("header_fix")
    if header_fix and isinstance(header_fix, dict):
        req_idx = header_fix.get("request_index")
        headers_to_add = header_fix.get("headers_to_add", [])
        headers_to_remove = header_fix.get("headers_to_remove", [])
        
        # Remove headers first
        for header_name in headers_to_remove:
            target_ep["headers"] = [
                h for h in target_ep["headers"]
                if h.get("key", "").lower() != header_name.lower()
            ]
        
        # Add/update headers
        for header in headers_to_add:
            header_key = header.get("key", "")
            header_value = header.get("value", "")
            
            # Check if header exists
            header_exists = False
            for existing_header in target_ep["headers"]:
                if existing_header.get("key", "").lower() == header_key.lower():
                    existing_header["value"] = header_value
                    header_exists = True
                    break
            
            if not header_exists:
                target_ep["headers"].append({
                    "key": header_key,
                    "value": header_value
                })
    
    # 4. Reconstruct logical flow
    base_think_time = test_plan.get("thread_group", {}).get("think_time", 1500)
    updated_flow = reconstruct_logical_flow(
        original_endpoints,
        llm_provider=llm_provider,
        llm_model=llm_model,
        base_think_time=base_think_time
    )
    test_plan["flow"] = updated_flow
```

---

## Current Capabilities

### Failure Types Handled

| Failure Type | Current Handling | AI Prompt |
|--------------|------------------|-----------|
| **401 Unauthorized** | ✅ Add extractor + replace hardcoded tokens | "401 Unauthorized usually means a missing JWT or Authorization header" |
| **Missing Bearer Token** | ✅ Trace token to upstream response, create extractor | "LOCATE Birth of Token: Find which response contains the token" |
| **Hardcoded JWT tokens** | ✅ Replace with `${c_token}` variable | "replacements: [{request_index, token_value, var_name}]" |
| **Missing Headers** | ✅ Add/update/remove headers | "header_fix: {request_index, headers_to_add, headers_to_remove}" |
| **Wrong Content-Type** | ✅ Auto-fix Content-Type | "415 Unsupported Media Type means wrong Content-Type header" |
| **CSRF Token Issues** | ⚠️ Limited handling | "CSRF token mismatch" |

### Remediation Types

| Remediation | Description | Example |
|-------------|-------------|---------|
| **Extractor Addition** | Add new extractor to upstream endpoint | `{"type": "json_extractor", "json_path": "$.token"}` |
| **Token Replacement** | Replace hardcoded tokens with variables | `{"token_value": "eyJhbG...", "var_name": "c_token"}` |
| **Header Injection** | Add missing headers to requests | `{"key": "Authorization", "value": "Bearer ${c_token}"}` |
| **Header Update** | Update existing headers | `{"key": "Content-Type", "value": "application/json"}` |
| **Header Removal** | Remove unnecessary headers | `"headers_to_remove": ["X-Deprecated"]` |

---

## AI Integration

### Supported LLM Providers

| Provider | Configuration | Default Model |
|----------|---------------|---------------|
| **Google Gemini** | `GEMINI_API_KEY` | gemini-2.0-flash |
| **Anthropic Claude** | `ANTHROPIC_API_KEY` | claude-3-opus-20240229 |
| **OpenAI GPT** | `OPENAI_API_KEY` | gpt-4 |
| **Grok** | `GROK_API_KEY` | grok-2 |
| **Groq** | `GROQ_API_KEY` | llama-3.3-70b-versatile |
| **GitHub Models** | `GITHUB_TOKEN` | gpt-4o |

### AI Prompt Structure

The AI prompt includes:

1. **Dry-Run Failure Log**: List of failures with sampler names, URLs, response codes
2. **Failed Requests Details**: Full request details from original capture
3. **Upstream History**: All preceding requests and responses
4. **Active Extractors**: Already configured extractor variables

### AI Response Schema

```json
{
    "diagnosis": "Why it failed, identify the root cause",
    "action_taken": "Detailed remediation action described clearly",
    "new_extractor": {
        "upstream_index": 0,
        "type": "json_extractor",
        "var_name": "c_token",
        "json_path": "$.access_token"
    },
    "replacements": [
        {
            "request_index": 5,
            "token_value": "eyJhbG...",
            "var_name": "c_token"
        }
    ],
    "header_fix": {
        "request_index": 5,
        "headers_to_add": [
            {"key": "Content-Type", "value": "application/json"}
        ],
        "headers_to_remove": ["X-Deprecated"]
    }
}
```

---

## Header Injection Feature

### Overview

The Header Injection feature allows the self-healing mechanism to automatically add, update, or remove HTTP headers in requests when dry-run failures occur.

### Use Cases

#### 1. Missing Content-Type (415 Error)

**Scenario:** Server returns `415 Unsupported Media Type` because the request is missing the `Content-Type` header.

**AI Diagnosis:**
```json
{
    "diagnosis": "415 Unsupported Media Type - Missing Content-Type header",
    "action_taken": "Added Content-Type header to request",
    "header_fix": {
        "request_index": 5,
        "headers_to_add": [
            {"key": "Content-Type", "value": "application/json"}
        ]
    }
}
```

#### 2. Missing Authorization Header (401 Error)

**Scenario:** Server returns `401 Unauthorized` because the request is missing the `Authorization` header.

**AI Diagnosis:**
```json
{
    "diagnosis": "401 Unauthorized - Missing Authorization header",
    "action_taken": "Added Authorization header with Bearer token variable",
    "new_extractor": {
        "upstream_index": 0,
        "type": "json_extractor",
        "var_name": "c_token",
        "json_path": "$.access_token"
    },
    "header_fix": {
        "request_index": 5,
        "headers_to_add": [
            {"key": "Authorization", "value": "Bearer ${c_token}"}
        ]
    }
}
```

#### 3. CSRF Token Header

**Scenario:** Server returns `403 Forbidden` due to CSRF token mismatch.

**AI Diagnosis:**
```json
{
    "diagnosis": "CSRF token mismatch - Missing X-CSRF-Token header",
    "action_taken": "Added CSRF token extractor and header",
    "new_extractor": {
        "upstream_index": 2,
        "type": "regex_extractor",
        "regex": "csrf_token.*?value=\"(.*?)\"",
        "var_name": "c_csrfToken"
    },
    "header_fix": {
        "request_index": 5,
        "headers_to_add": [
            {"key": "X-CSRF-Token", "value": "${c_csrfToken}"}
        ]
    }
}
```

### Header Operations

| Operation | Description | Example |
|-----------|-------------|---------|
| **Add Header** | Add new header to request | `{"key": "X-Custom", "value": "value"}` |
| **Update Header** | Update existing header value | `{"key": "Content-Type", "value": "application/json"}` |
| **Remove Header** | Remove unnecessary header | `"headers_to_remove": ["X-Deprecated"]` |
| **Multiple Headers** | Add/update multiple headers at once | Array of header objects |
| **Variable Support** | Use JMeter variables in values | `"value": "Bearer ${c_token}"` |

---

## Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `JMETER_BIN` | Path to JMeter binary | `C:\apache-jmeter-5.3\bin\jmeter.bat` |
| `JMETER_TIMEOUT_SECONDS` | Dry-run timeout | `120` |
| `LLM_PROVIDER` | AI provider to use | `gemini` |
| `LLM_MODEL` | AI model to use | Provider-specific |

### Self-Healing Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `max_retries` | Maximum healing iterations | `3` |
| `users` | Number of users for dry-run | `1` |
| `ramp_up` | Ramp-up time for dry-run | `1` second |
| `loops` | Number of iterations for dry-run | `1` |

---

## Use Cases and Examples

### Example 1: JWT Token Correlation

**Input:**
- POST `/auth/login` returns `{"token": "eyJhbG..."}`
- GET `/api/users` uses hardcoded `Authorization: Bearer eyJhbG...`

**Dry-Run Result:** 401 Unauthorized on GET `/api/users`

**AI Diagnosis:**
```json
{
    "diagnosis": "401 Unauthorized - Bearer token expired or missing",
    "action_taken": "Added JSON extractor to extract token from login response",
    "new_extractor": {
        "upstream_index": 0,
        "type": "json_extractor",
        "var_name": "c_token",
        "json_path": "$.token"
    },
    "replacements": [
        {
            "request_index": 1,
            "token_value": "eyJhbG...",
            "var_name": "c_token"
        }
    ]
}
```

**Result:** Token extracted dynamically, downstream requests use `${c_token}`

### Example 2: Content-Type Fix

**Input:**
- POST `/api/data` with JSON body but missing `Content-Type` header

**Dry-Run Result:** 415 Unsupported Media Type

**AI Diagnosis:**
```json
{
    "diagnosis": "415 Unsupported Media Type - Missing Content-Type header",
    "action_taken": "Added Content-Type header",
    "header_fix": {
        "request_index": 2,
        "headers_to_add": [
            {"key": "Content-Type", "value": "application/json"}
        ]
    }
}
```

**Result:** Content-Type header added, request succeeds

### Example 3: Combined Fix

**Input:**
- POST `/api/data` with missing Content-Type AND hardcoded token

**Dry-Run Result:** 401 Unauthorized AND 415 Unsupported Media Type

**AI Diagnosis:**
```json
{
    "diagnosis": "Multiple issues: Missing Authorization header and Content-Type",
    "action_taken": "Added token extractor, Authorization header, and Content-Type header",
    "new_extractor": {
        "upstream_index": 0,
        "type": "json_extractor",
        "var_name": "c_token",
        "json_path": "$.access_token"
    },
    "replacements": [
        {
            "request_index": 2,
            "token_value": "eyJhbG...",
            "var_name": "c_token"
        }
    ],
    "header_fix": {
        "request_index": 2,
        "headers_to_add": [
            {"key": "Authorization", "value": "Bearer ${c_token}"},
            {"key": "Content-Type", "value": "application/json"}
        ]
    }
}
```

**Result:** Both issues fixed in single iteration

---

## Limitations

### Current Limitations

| Limitation | Description | Workaround |
|------------|-------------|------------|
| **Max 3 Retries** | Self-healing stops after 3 iterations | Manual intervention required |
| **AI Dependency** | Requires configured LLM for diagnosis | Deterministic fallback available |
| **Token-Only Focus** | Primarily handles token/header issues | Other failures return diagnosis only |
| **No Rate Limiting** | Doesn't handle 429 Too Many Requests | Manual backoff configuration |
| **No SSL Handling** | Doesn't fix SSL certificate errors | Pre-configure truststore |
| **No DNS Handling** | Doesn't fix DNS resolution failures | Pre-configure DNS settings |

### Deterministic Fallback

When AI is not configured, the system uses deterministic logic:

1. **XML Validation**: Checks JMX structure
2. **Basic Token Detection**: Identifies high-entropy values
3. **Regex-Based Extraction**: Creates boundary/regex extractors
4. **Sequential Grouping**: Groups requests sequentially

---

## Future Enhancements

### Planned Features

| Feature | Priority | Description |
|---------|----------|-------------|
| **CSRF Token Handling** | High | Extract and inject CSRF tokens |
| **Cookie Extraction** | Medium | Extract session cookies from responses |
| **Retry Logic** | Medium | Handle 429 Too Many Requests with backoff |
| **Timeout Configuration** | Low | Auto-configure connection/response timeouts |
| **SSL Certificate Handling** | Low | Trust-all certificates for testing |
| **Response Assertions** | Low | Add response validation assertions |

### Advanced Features

| Feature | Description |
|---------|-------------|
| **Multi-Failure Diagnosis** | Handle multiple failure types in single iteration |
| **Learning Mode** | Remember past fixes for similar failures |
| **Custom Rules** | Allow user-defined healing rules |
| **Performance Optimization** | Reduce AI calls for common failures |
| **Parallel Execution** | Run multiple healing attempts simultaneously |

---

## Conclusion

The Self-Healing Mechanism provides an intelligent, automated approach to fixing common JMeter script issues. By combining AI-powered diagnosis with deterministic fallback logic, it significantly reduces the time and effort required to create production-ready performance test scripts.

The header injection feature further enhances the system's ability to handle a wide range of failure scenarios, making it a comprehensive solution for automated script validation and remediation.

---

*Document Version: 1.0*
*Last Updated: 2026-06-15*
*Author: Technical Documentation Team*
