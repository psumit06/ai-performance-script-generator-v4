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

def process_request(item, endpoints, folder_path=None):
    request = item.get("request", {})
    endpoint = create_endpoint_schema()
    folder_path = folder_path or []
    endpoint["source_index"] = len(endpoints)
    endpoint["transaction_hint"] = " / ".join(folder_path)

    # Name
    endpoint["name"] = convert_vars(item.get("name", "Unnamed Request"))

    # Method
    endpoint["method"] = request.get("method", "GET")

    # URL
    raw_url = request.get("url", {})
    if isinstance(raw_url, dict):
        full_url = raw_url.get("raw") or ""
    else:
        full_url = str(raw_url) if raw_url else ""

    # Convert Postman variable syntax to JMeter syntax in URL
    full_url = convert_vars(full_url)
    endpoint["full_url"] = full_url

    parsed = urlparse(full_url)
    endpoint["protocol"] = parsed.scheme or ""
    endpoint["host"] = parsed.hostname or ""
    endpoint["port"] = str(parsed.port or "")
    endpoint["path"] = parsed.path or "/"

    if isinstance(raw_url, dict):
        protocol = raw_url.get("protocol")
        host = raw_url.get("host")
        path = raw_url.get("path")
        if not endpoint["protocol"] and protocol:
            endpoint["protocol"] = convert_vars(protocol)
        if not endpoint["host"] and host:
            endpoint["host"] = convert_vars(".".join(host) if isinstance(host, list) else str(host))
        if (not parsed.path or parsed.path == "/") and path:
            path_value = "/".join(path) if isinstance(path, list) else str(path)
            endpoint["path"] = "/" + convert_vars(path_value).lstrip("/")

    # If the URL had variables and urlparse failed to separate them nicely,
    # let's try a heuristic: if protocol is empty but full_url starts with ${,
    # we can try to keep full_url as path or keep it intact.
    # JMeter's HTTP Sampler handles a full URL path like ${base_url}/path perfectly if domain/protocol are empty!

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

    endpoint["headers"] = normalized_headers
    endpoint["content_type"] = content_type

    # Body
    body = request.get("body", {})
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

def process_items(items, endpoints, folder_path=None):
    folder_path = folder_path or []
    for item in items:
        # FOLDER DETECTED
        if "item" in item:
            process_items(item["item"], endpoints, folder_path + [convert_vars(item.get("name", "Folder"))])
        # ACTUAL REQUEST
        elif "request" in item:
            process_request(item, endpoints, folder_path)

def parse_postman_collection(content):
    data = json.loads(content)
    endpoints = []
    items = data.get("item", [])
    process_items(items, endpoints)
    return {
        "type": "postman",
        "endpoints": endpoints
    }
