import os
import json
import re
from app.services.llm_provider import extract_json_object, generate_text, get_llm_config, is_llm_available

def filter_traffic_with_ai(endpoints, llm_provider=None, llm_model=None):
    """
    Cognitively filters third-party bloat, analytics, fonts, and static resources
    using the configured LLM provider while preserving core APIs and user transactions.
    Also generates a clean regex for URL exclusions in JMeter.
    """
    if not endpoints:
        return [], ""

    # 1. Base Deterministic Filtering (Quick Exclusions to reduce prompt tokens)
    # We will flag obvious third-party analytics and tracking endpoints
    obvious_noise_domains = [
        "google-analytics.com", "googletagmanager.com", "analytics.google.com",
        "facebook.net", "connect.facebook.net", "doubleclick.net",
        "hotjar.com", "hotjar.io", "mixpanel.com", "sentry.io",
        "browser-update.org", "optimizely.com", "clarity.ms"
    ]
    
    pre_filtered_list = []
    noise_count = 0
    
    for idx, ep in enumerate(endpoints):
        url = ep.get("full_url", "")
        is_noise = False
        for domain in obvious_noise_domains:
            if domain in url.lower():
                is_noise = True
                break
        
        if is_noise:
            noise_count += 1
            # Keep it in metadata but flag as skip
            ep["ai_decision"] = {"keep": False, "reason": "Deterministic third-party analytics exclusion"}
        else:
            pre_filtered_list.append((idx, ep))

    # If all filtered or none left, return
    if not pre_filtered_list:
        return [ep for ep in endpoints if ep.get("ai_decision", {}).get("keep", True)], "(?i).*\\.(bmp|css|js|gif|ico|png|woff2)"

    # Prepare prompt for the configured LLM.
    # We only send method and URL to save token space, along with content_type
    prompt_payload = []
    for idx, ep in pre_filtered_list:
        prompt_payload.append({
            "index": idx,
            "method": ep.get("method", ""),
            "url": ep.get("full_url", ""),
            "content_type": ep.get("content_type", "")
        })

    prompt = f"""
    You are an expert Performance Engineer and Traffic Architect.
    Analyze the following list of captured HTTP requests from a browser/Postman recording.
    Your goal is to perform "Smart Noise Reduction" and identify core business actions and functional application APIs.
    
    We want to DISCARD/FILTER OUT:
    1. Static assets (images, web fonts, CSS files, plain JS files, browser icons) UNLESS they are critical API endpoints.
    2. Third-party integrations that distort performance benchmarks (e.g. CDNs, tracking pixels, ads, maps, fonts, static content hosts).
    
    We want to KEEP:
    1. Core application APIs (JSON/XML/GraphQL payloads).
    2. Document loads (HTML pages representing base entry points).
    3. Custom backend webhooks or server-to-server APIs.

    Analyze these requests:
    {json.dumps(prompt_payload, indent=2)}

    Respond with a strictly formatted JSON object containing:
    1. "results": a list of objects, one for each input request index:
       - "index": (integer) matching the input index.
       - "keep": (boolean) true if core application action/API, false if bloat/static/third-party.
       - "reason": (string) a concise justification.
    2. "exclusion_regex": (string) A single combined Java-compatible regex pattern to exclude static assets in JMeter's HTTP Request Defaults (e.g., "(?i).*\\.(bmp|css|js|gif|ico|jpe?g|png|woff2?|svg|less)"). Ensure it matches standard formats but includes any specific extension patterns observed in the filtered requests.

    Return ONLY the valid raw JSON object. Do not include markdown wraps or anything else.
    """

    try:
        if not is_llm_available(llm_provider):
            config = get_llm_config(provider=llm_provider, model=llm_model)
            raise RuntimeError(f"AI traffic filter skipped because provider '{config['provider']}' is not configured.")
        text = generate_text(prompt, provider=llm_provider, model=llm_model)
        ai_data = extract_json_object(text)
        results = ai_data.get("results", [])
        exclusion_regex = ai_data.get("exclusion_regex", "(?i).*\\.(bmp|css|js|gif|ico|png|woff2)")
        
        # Apply decisions
        ai_decision_map = {res["index"]: res for res in results}
        
        filtered_endpoints = []
        for idx, ep in enumerate(endpoints):
            if idx in ai_decision_map:
                decision = ai_decision_map[idx]
                ep["ai_decision"] = {
                    "keep": decision.get("keep", True),
                    "reason": decision.get("reason", "AI Classification")
                }
            elif "ai_decision" not in ep:
                ep["ai_decision"] = {
                    "keep": True,
                    "reason": "Default Keep (No AI Classification result)"
                }
            
            if ep["ai_decision"]["keep"]:
                filtered_endpoints.append(ep)
                
        return filtered_endpoints, exclusion_regex

    except Exception as e:
        print(f"AI Traffic Filtering failed: {e}. Falling back to default deterministic filtering.")
        
        # Fallback regex and filter logic
        default_regex = "(?i).*\\.(bmp|css|js|gif|ico|jpe?g|png|woff2?|svg|less)"
        filtered_endpoints = []
        
        static_ext_pattern = re.compile(r"\.(bmp|css|js|gif|ico|jpe?g|png|woff2?|svg|less)(\?.*)?$", re.IGNORECASE)
        
        for ep in endpoints:
            url = ep.get("full_url", "")
            # Check static extension
            is_static = bool(static_ext_pattern.search(url))
            
            # Check deterministic domain exclusions
            is_noise = False
            for domain in obvious_noise_domains:
                if domain in url.lower():
                    is_noise = True
                    break
                    
            if not is_static and not is_noise:
                ep["ai_decision"] = {"keep": True, "reason": "Deterministic pass"}
                filtered_endpoints.append(ep)
            else:
                ep["ai_decision"] = {"keep": False, "reason": "Deterministic static/third-party exclusion"}
                
        return filtered_endpoints, default_regex
