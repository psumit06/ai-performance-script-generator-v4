import json
import base64
from urllib.parse import urlparse, parse_qs
from app.services.normalized_schema import create_endpoint_schema

def parse_har(raw_content):
    data = json.loads(raw_content)
    entries = data.get("log", {}).get("entries", [])
    
    endpoints = []
    
    for index, entry in enumerate(entries):
        request = entry.get("request", {})
        response = entry.get("response", {})
        
        # Skip requests if there's no URL
        full_url = request.get("url", "")
        if not full_url:
            continue
            
        endpoint = create_endpoint_schema()
        endpoint["source_index"] = index
        
        # Method & URL
        endpoint["method"] = request.get("method", "GET")
        endpoint["full_url"] = full_url
        
        parsed = urlparse(full_url)
        endpoint["protocol"] = parsed.scheme or "http"
        endpoint["host"] = parsed.hostname or ""
        endpoint["port"] = parsed.port or ""
        if not endpoint["port"]:
            endpoint["port"] = "443" if endpoint["protocol"] == "https" else "80"
        endpoint["path"] = parsed.path or "/"
        
        # Name (use path if no descriptive name exists)
        endpoint["name"] = f"{endpoint['method']} {endpoint['path']}"
        
        # Timing metadata
        endpoint["startedDateTime"] = entry.get("startedDateTime", "")
        endpoint["duration"] = entry.get("time", 0)
        
        # Query Params
        query_params = []
        har_query = request.get("queryString", [])
        if har_query:
            for item in har_query:
                query_params.append({
                    "key": item.get("name", ""),
                    "value": item.get("value", ""),
                    "enabled": True
                })
        else:
            # Fallback to parsing from URL
            query_dict = parse_qs(parsed.query)
            for key, values in query_dict.items():
                for val in values:
                    query_params.append({
                        "key": key,
                        "value": val,
                        "enabled": True
                    })
        endpoint["query_params"] = query_params
        
        # Headers
        headers = []
        content_type = ""
        for header in request.get("headers", []):
            key = header.get("name", "")
            val = header.get("value", "")
            headers.append({
                "key": key,
                "value": val
            })
            if key.lower() == "content-type":
                content_type = val
        endpoint["headers"] = headers
        endpoint["content_type"] = content_type

        # Cookies are often where session lineage hides in browser captures.
        if request.get("cookies"):
            cookie_value = "; ".join(
                f"{cookie.get('name', '')}={cookie.get('value', '')}"
                for cookie in request.get("cookies", [])
                if cookie.get("name")
            )
            if cookie_value and not any(h["key"].lower() == "cookie" for h in headers):
                endpoint["headers"].append({"key": "Cookie", "value": cookie_value})
        
        # Request Body
        post_data = request.get("postData", {})
        body_mime = post_data.get("mimeType", "")
        body_text = post_data.get("text", "")
        
        if post_data:
            if "application/json" in body_mime.lower() or "text/" in body_mime.lower() or "application/xml" in body_mime.lower():
                endpoint["body_mode"] = "raw"
                endpoint["raw_body"] = body_text
            elif "application/x-www-form-urlencoded" in body_mime.lower():
                endpoint["body_mode"] = "urlencoded"
                urlencoded_params = []
                # Check if params list is populated
                har_params = post_data.get("params", [])
                if har_params:
                    for param in har_params:
                        urlencoded_params.append({
                            "key": param.get("name", ""),
                            "value": param.get("value", "")
                        })
                else:
                    # Parse from raw text
                    parsed_body = parse_qs(body_text)
                    for key, values in parsed_body.items():
                        for val in values:
                            urlencoded_params.append({
                                "key": key,
                                "value": val
                            })
                endpoint["urlencoded"] = urlencoded_params
            elif "multipart/form-data" in body_mime.lower():
                endpoint["body_mode"] = "formdata"
                form_fields = []
                for param in post_data.get("params", []):
                    form_fields.append({
                        "key": param.get("name", ""),
                        "value": param.get("value", "")
                    })
                endpoint["form_data"] = form_fields
            else:
                if body_text:
                    endpoint["body_mode"] = "raw"
                    endpoint["raw_body"] = body_text
                    
        # Response Metadata (essential for AI Lineage and self-healing validation)
        endpoint["status_code"] = response.get("status", 200)
        
        response_headers = []
        for header in response.get("headers", []):
            response_headers.append({
                "key": header.get("name", ""),
                "value": header.get("value", "")
            })
        endpoint["response_headers"] = response_headers
        
        response_content = response.get("content", {})
        response_body = response_content.get("text", "")
        if response_content.get("encoding") == "base64" and response_body:
            try:
                response_body = base64.b64decode(response_body).decode("utf-8", errors="replace")
            except Exception:
                pass
        endpoint["response_body"] = response_body
        endpoint["response_mime_type"] = response_content.get("mimeType", "")
        
        endpoints.append(endpoint)
        
    return {
        "type": "har",
        "endpoints": endpoints
    }
