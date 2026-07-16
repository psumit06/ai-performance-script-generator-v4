import json
import base64
from urllib.parse import urlparse, parse_qs
from app.services.normalized_schema import create_endpoint_schema

# Custom headers added by our Chrome extension for transaction markers
EXT_TX_HEADER = "x-transaction-name"
EXT_TX_START_HEADER = "x-transaction-start"
EXT_TX_END_HEADER = "x-transaction-end"


def parse_har(raw_content):
    data = json.loads(raw_content)
    log = data.get("log", {})
    entries = log.get("entries", [])

    # ── Step 1: Parse pages[] for page-level grouping ──────────────────────
    pages = log.get("pages", [])
    page_map = {}  # pageref -> {title, index}
    for i, page in enumerate(pages):
        page_id = page.get("id", "")
        page_title = page.get("title", f"Page {i + 1}")
        if page_id:
            page_map[page_id] = {"title": page_title, "index": i}

    # ── Step 2: Parse entries ──────────────────────────────────────────────
    endpoints = []

    for index, entry in enumerate(entries):
        request = entry.get("request", {})
        response = entry.get("response", {})

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

        # Name
        endpoint["name"] = f"{endpoint['method']} {endpoint['path']}"

        # Timing metadata
        endpoint["startedDateTime"] = entry.get("startedDateTime", "")
        endpoint["duration"] = entry.get("time", 0)

        # ── HAR page reference ─────────────────────────────────────────────
        pageref = entry.get("pageref", "")
        if pageref and pageref in page_map:
            endpoint["transaction_hint"] = page_map[pageref]["title"]
            endpoint["_page_index"] = page_map[pageref]["index"]
        else:
            endpoint["transaction_hint"] = ""
            endpoint["_page_index"] = -1

        # ── Chrome extension fields (if present) ───────────────────────────
        endpoint["_resourceType"] = entry.get("_resourceType", "")
        endpoint["_initiator"] = entry.get("_initiator", "")

        # ── Custom transaction headers from our extension ──────────────────
        headers = []
        content_type = ""
        ext_tx_name = ""
        for header in request.get("headers", []):
            key = header.get("name", "")
            val = header.get("value", "")
            headers.append({"key": key, "value": val})
            if key.lower() == "content-type":
                content_type = val
            # Detect our extension's custom headers
            if key.lower() == EXT_TX_HEADER:
                ext_tx_name = val
            if key.lower() == EXT_TX_START_HEADER and val.lower() == "true":
                endpoint["_ext_tx_start"] = True
            if key.lower() == EXT_TX_END_HEADER and val.lower() == "true":
                endpoint["_ext_tx_end"] = True

        endpoint["headers"] = headers
        endpoint["content_type"] = content_type

        # If extension header is present, override transaction_hint
        if ext_tx_name:
            endpoint["transaction_hint"] = ext_tx_name

        # Cookies
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
                har_params = post_data.get("params", [])
                if har_params:
                    for param in har_params:
                        urlencoded_params.append({
                            "key": param.get("name", ""),
                            "value": param.get("value", "")
                        })
                else:
                    parsed_body = parse_qs(body_text)
                    for key, values in parsed_body.items():
                        for val in values:
                            urlencoded_params.append({"key": key, "value": val})
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

        # Response Metadata
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

    # ── Step 3: Build page-based transactions if pages[] was present ───────
    has_pages = len(page_map) > 0
    has_ext_headers = any(ep.get("transaction_hint") for ep in endpoints)

    if has_pages and not has_ext_headers:
        # Group by page, preserving chronological order
        _assign_page_transactions(endpoints)

    return {
        "type": "har",
        "endpoints": endpoints,
        "has_page_data": has_pages,
        "has_ext_markers": has_ext_headers,
    }


def _assign_page_transactions(endpoints):
    """
    Ensure transaction_hint is set from page data for all endpoints.
    Endpoints without a pageref inherit the nearest page context.
    """
    current_page = ""
    for ep in endpoints:
        page_hint = ep.get("transaction_hint", "")
        if page_hint:
            current_page = page_hint
        elif current_page:
            ep["transaction_hint"] = current_page
