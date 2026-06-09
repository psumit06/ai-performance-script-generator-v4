import json
import re
from urllib.parse import (
    urlparse,
    parse_qs
)
from app.services.normalized_schema import (
    create_endpoint_schema
)

def convert_vars(text):
    if text is None:
        return ""
    if not isinstance(text, str):
        return str(text)
    # Convert {{variable}} to ${variable}
    return re.sub(r'\{\{([^}]+)\}\}', r'${\1}', text)

def collection_variables(data):
    variables = {}
    for item in data.get("variable", []) or []:
        key = item.get("key")
        if key:
            variables[key] = item.get("value", "")
    return variables

def variable_name_from_postman_value(value):
    if not isinstance(value, str):
        return ""
    match = re.fullmatch(r"\{\{([^}]+)\}\}", value.strip())
    return match.group(1) if match else ""

def resolve_protocol_host(postman_protocol, postman_host, variables):
    protocol = convert_vars(postman_protocol) if postman_protocol else ""
    host = convert_vars(".".join(postman_host) if isinstance(postman_host, list) else str(postman_host))

    host_parts = postman_host if isinstance(postman_host, list) else [str(postman_host)]
    if len(host_parts) == 1:
        variable_name = variable_name_from_postman_value(host_parts[0])
        variable_value = variables.get(variable_name, "")
        parsed_variable = urlparse(variable_value)
        if parsed_variable.scheme and parsed_variable.hostname:
            return parsed_variable.scheme, parsed_variable.hostname, str(parsed_variable.port or "")

    return protocol or "https", host, ""

def process_request(item, endpoints, folder_path=None, variables=None):
    request = item.get("request", {})
    if not isinstance(request, dict):
        request = {}
    endpoint = create_endpoint_schema()
    folder_path = folder_path or []
    variables = variables or {}
    endpoint["source_index"] = len(endpoints)
    endpoint["transaction_hint"] = " / ".join(folder_path)

    # Name
    endpoint["name"] = convert_vars(item.get("name", "Unnamed Request"))

    # Method
    endpoint["method"] = request.get("method", "GET")

    # URL
    raw_url = request.get("url", {})
    if not isinstance(raw_url, dict):
        raw_url = {"raw": str(raw_url) if raw_url else ""}
    full_url = raw_url.get("raw") or ""

    # Convert Postman variable syntax to JMeter syntax in URL
    full_url = convert_vars(full_url)
    endpoint["full_url"] = full_url

    # If Postman has structured URL components, use them directly
    # (urlparse fails on variable expressions like ${host}/booking)
    parsed = urlparse(full_url)
    if isinstance(raw_url, dict) and raw_url.get("host"):
        postman_host = raw_url.get("host")
        postman_path = raw_url.get("path")
        postman_protocol = raw_url.get("protocol")

        endpoint["protocol"], endpoint["host"], endpoint["port"] = resolve_protocol_host(
            postman_protocol,
            postman_host,
            variables
        )
        if postman_path:
            path_value = "/".join(postman_path) if isinstance(postman_path, list) else str(postman_path)
            endpoint["path"] = "/" + convert_vars(path_value).lstrip("/")
        else:
            endpoint["path"] = "/"
    else:
        # Fallback to urlparse for non-variable URLs
        endpoint["protocol"] = parsed.scheme or ""
        endpoint["host"] = parsed.hostname or ""
        endpoint["port"] = str(parsed.port or "")
        endpoint["path"] = parsed.path or "/"

    # Query Params
    query_params = []
    # If the Postman url has query array, use it
    if isinstance(raw_url, dict) and "query" in raw_url:
        for q in raw_url.get("query", []):
            query_params.append({
                "key": convert_vars(q.get("key", "")),
                "value": convert_vars(q.get("value", "")),
                "enabled": not q.get("disabled", False)
            })
    else:
        # Fallback to parsing from parsed query string
        query_dict = parse_qs(parsed.query)
        for key, values in query_dict.items():
            for value in values:
                query_params.append({
                    "key": convert_vars(key),
                    "value": convert_vars(value),
                    "enabled": True
                })
    endpoint["query_params"] = query_params

    # Headers
    headers = request.get("header", [])
    normalized_headers = []
    content_type = ""

    for header in headers:
        # Skip disabled headers
        if header.get("disabled", False):
            continue
        key = convert_vars(header.get("key") or "")
        value = convert_vars(header.get("value") or "")
        normalized_headers.append({
            "key": key,
            "value": value
        })
        if key.lower() == "content-type":
            content_type = value

    # Parse Postman auth block and inject Authorization header
    auth = request.get("auth", {})
    if not isinstance(auth, dict):
        auth = {}
    auth_type = auth.get("type", "")
    if auth_type == "bearer":
        bearer_list = auth.get("bearer", [])
        for b in bearer_list:
            if b.get("key") == "token":
                token_val = convert_vars(b.get("value") or "")
                if token_val:
                    # Remove existing Authorization header if present
                    normalized_headers = [h for h in normalized_headers if h["key"].lower() != "authorization"]
                    normalized_headers.append({"key": "Authorization", "value": f"Bearer {token_val}"})
                    break
    elif auth_type == "basic":
        basic_list = auth.get("basic", [])
        username = ""
        password = ""
        for b in basic_list:
            if b.get("key") == "username":
                username = convert_vars(b.get("value") or "")
            elif b.get("key") == "password":
                password = convert_vars(b.get("value") or "")
        if username:
            import base64
            cred = base64.b64encode(f"{username}:{password}".encode()).decode()
            normalized_headers = [h for h in normalized_headers if h["key"].lower() != "authorization"]
            normalized_headers.append({"key": "Authorization", "value": f"Basic {cred}"})

    endpoint["headers"] = normalized_headers
    endpoint["content_type"] = content_type

    # Body
    body = request.get("body", {})
    if not isinstance(body, dict):
        body = {}
    body_mode = body.get("mode", "")
    endpoint["body_mode"] = body_mode

    # RAW
    if body_mode == "raw":
        endpoint["raw_body"] = convert_vars(body.get("raw") or "")
    # FORM DATA
    elif body_mode == "formdata":
        form_data = body.get("formdata") or []
        normal_fields = []
        multipart_files = []
        for form_item in form_data:
            if form_item.get("disabled", False):
                continue
            item_type = form_item.get("type", "text")
            if item_type == "file":
                multipart_files.append({
                    "key": convert_vars(form_item.get("key") or ""),
                    "src": convert_vars(form_item.get("src") or "")
                })
            else:
                normal_fields.append({
                    "key": convert_vars(form_item.get("key") or ""),
                    "value": convert_vars(form_item.get("value") or "")
                })
        endpoint["form_data"] = normal_fields
        endpoint["multipart_files"] = multipart_files
    # URLENCODED
    elif body_mode == "urlencoded":
        urlencoded = body.get("urlencoded") or []
        normal_fields = []
        for url_item in urlencoded:
            if url_item.get("disabled", False):
                continue
            normal_fields.append({
                "key": convert_vars(url_item.get("key") or ""),
                "value": convert_vars(url_item.get("value") or "")
            })
        endpoint["urlencoded"] = normal_fields
    # GRAPHQL
    elif body_mode == "graphql":
        graphql_data = body.get("graphql", {})
        endpoint["graphql"] = {
            "query": convert_vars(graphql_data.get("query", "")),
            "variables": convert_vars(graphql_data.get("variables", ""))
        }
        # For JMeter, GraphQL is sent as raw JSON body
        endpoint["body_mode"] = "raw"
        endpoint["raw_body"] = convert_vars(json.dumps({
            "query": graphql_data.get("query", ""),
            "variables": json.loads(graphql_data.get("variables", "{}")) if graphql_data.get("variables") else {}
        }))
        if not content_type:
            endpoint["content_type"] = "application/json"
            endpoint["headers"].append({"key": "Content-Type", "value": "application/json"})

    endpoints.append(endpoint)

def process_items(items, endpoints, folder_path=None, variables=None):
    folder_path = folder_path or []
    variables = variables or {}
    for item in items:
        if not isinstance(item, dict):
            continue
        # FOLDER DETECTED
        if "item" in item:
            process_items(item["item"], endpoints, folder_path + [convert_vars(item.get("name", "Folder"))], variables)
        # ACTUAL REQUEST
        elif "request" in item:
            process_request(item, endpoints, folder_path, variables)

def parse_postman_collection(content):
    data = json.loads(content)
    endpoints = []
    items = data.get("item", [])
    process_items(items, endpoints, variables=collection_variables(data))
    return {
        "type": "postman",
        "endpoints": endpoints
    }
