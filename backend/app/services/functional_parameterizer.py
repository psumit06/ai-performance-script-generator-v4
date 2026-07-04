import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
TIMESTAMP_RE = re.compile(r"\b(20\d{8,12})\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b[6-9]\d{9}\b")
JMETER_EXPR_RE = re.compile(r"\$\{[^}]+\}")

UUID_FIELD_TOKENS = ("id", "uuid", "guid", "interaction", "correlation", "trace", "key", "token", "session")
TIMESTAMP_FIELD_TOKENS = ("timestamp", "datetime", "date", "time", "created", "updated", "modified", "ordered")
EMAIL_FIELD_TOKENS = ("email", "mail")
PHONE_FIELD_TOKENS = ("phone", "mobile", "tel", "contact")


def load_rules_json(raw_rules: Optional[str]) -> Dict[str, Any]:
    if not raw_rules or not raw_rules.strip():
        return {"rules": []}
    data = json.loads(raw_rules)
    if isinstance(data, dict) and "rules" in data:
        return data
    if isinstance(data, dict):
        return {
            "rules": [
                {
                    "name": key,
                    "field_patterns": [key],
                    "replacement": value,
                    "auto_apply": True,
                }
                for key, value in data.items()
            ]
        }
    raise ValueError("Replacement rules JSON must be an object.")


def candidate_id(candidate: Dict[str, Any]) -> str:
    raw = "|".join(str(candidate.get(key, "")) for key in (
        "request_index",
        "location",
        "field_path",
        "original_value",
    ))
    return "param_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def has_jmeter_expression(value: str) -> bool:
    return bool(JMETER_EXPR_RE.search(value or ""))


def field_matches(field_path: str, patterns: List[str]) -> bool:
    field = (field_path or "").lower()
    return any((pattern or "").lower() in field for pattern in patterns or [])


def value_matches(value: str, pattern: str) -> bool:
    if not pattern:
        return True
    if pattern == "uuid":
        return bool(UUID_RE.search(value))
    if pattern == "email":
        return bool(EMAIL_RE.search(value))
    if pattern == "phone":
        return bool(PHONE_RE.search(value))
    if pattern == "timestamp_14":
        return bool(TIMESTAMP_RE.search(value))
    if pattern == "timestamp_12":
        return bool(TIMESTAMP_RE.search(value))
    return False


def _field_has_tokens(field_path: str, tokens: tuple) -> bool:
    lower = (field_path or "").lower()
    return any(token in lower for token in tokens)


def add_candidate(candidates: List[Dict[str, Any]], candidate: Dict[str, Any]):
    if not candidate.get("original_value") or has_jmeter_expression(candidate.get("original_value", "")):
        return
    candidate["id"] = candidate_id(candidate)
    if not any(existing["id"] == candidate["id"] for existing in candidates):
        candidates.append(candidate)


def candidate_base(endpoint: Dict[str, Any], location: str, field_path: str, original_value: str):
    return {
        "request_index": endpoint.get("source_index", 0),
        "request_name": endpoint.get("name", ""),
        "location": location,
        "field_path": field_path,
        "original_value": original_value,
    }


def detect_rule_candidates(endpoint: Dict[str, Any], text: str, location: str, field_path: str, rules: List[Dict[str, Any]]):
    candidates = []
    text_str = str(text) if text is not None else ""
    for rule in rules or []:
        replacement = rule.get("replacement")
        if not replacement:
            continue
        patterns = rule.get("field_patterns") or [rule.get("field_pattern", "")]
        value_regex = rule.get("value_regex")
        value_pattern = rule.get("value_pattern", "")
        if patterns and not field_matches(field_path, patterns):
            continue

        matches = []
        if value_regex:
            matches = [match.group(0) for match in re.finditer(value_regex, text_str)]
        elif value_pattern and value_matches(text_str, value_pattern):
            match = re.search(UUID_RE if value_pattern == "uuid" else re.escape(text_str), text_str)
            matches = [match.group(0)] if match else [text_str]
        elif not value_pattern:
            matches = [text_str]

        for original_value in matches:
            candidate = candidate_base(endpoint, location, field_path, original_value)
            candidate.update({
                "replacement": replacement,
                "reason": rule.get("reason") or f"Matched replacement rule: {rule.get('name', field_path)}",
                "confidence": rule.get("confidence", "high"),
                "source": "rule",
                "selected_by_default": bool(rule.get("auto_apply", True)),
                "auto_apply": bool(rule.get("auto_apply", True)),
            })
            add_candidate(candidates, candidate)
    return candidates


def detect_auto_candidates(endpoint: Dict[str, Any], text: str, location: str, field_path: str):
    candidates = []
    text_str = str(text) if text is not None else ""
    if not text_str or has_jmeter_expression(text_str):
        return candidates

    lower_field = (field_path or "").lower()
    field_is_uuid = _field_has_tokens(field_path, UUID_FIELD_TOKENS)
    field_is_ts = _field_has_tokens(field_path, TIMESTAMP_FIELD_TOKENS)
    field_is_email = _field_has_tokens(field_path, EMAIL_FIELD_TOKENS)
    field_is_phone = _field_has_tokens(field_path, PHONE_FIELD_TOKENS)

    for match in UUID_RE.finditer(text_str):
        if field_is_uuid:
            conf = "high"
            reason = "UUID-like value in ID/correlation field"
        else:
            conf = "medium"
            reason = "UUID-like value detected"
        candidate = candidate_base(endpoint, location, field_path, match.group(0))
        candidate.update({
            "replacement": "${__UUID()}",
            "reason": reason,
            "confidence": conf,
            "source": "auto_detected",
            "selected_by_default": conf == "extremely_high",
            "auto_apply": False,
        })
        add_candidate(candidates, candidate)

    for match in TIMESTAMP_RE.finditer(text_str):
        ts_len = len(match.group(1))
        if field_is_ts:
            conf = "high"
        else:
            conf = "medium"
        fmt = {10: "yyyyMMddHH", 11: "yyyyMMddHHm", 12: "yyyyMMddHHmm", 13: "yyyyMMddHHmmS", 14: "yyyyMMddHHmmss"}.get(ts_len, "yyyyMMddHHmm")
        replacement = f"${{__time({fmt},)}}"
        candidate = candidate_base(endpoint, location, field_path, match.group(1))
        candidate.update({
            "replacement": replacement,
            "reason": f"{ts_len}-digit timestamp-like value",
            "confidence": conf,
            "source": "auto_detected",
            "selected_by_default": conf == "extremely_high",
            "auto_apply": False,
        })
        add_candidate(candidates, candidate)

    for match in EMAIL_RE.finditer(text_str):
        conf = "high" if field_is_email else "medium"
        reason = "Email-like value in email field" if field_is_email else "Email-like value detected"
        candidate = candidate_base(endpoint, location, field_path, match.group(0))
        candidate.update({
            "replacement": "user_${__threadNum}_${__time()}@test.com",
            "reason": reason,
            "confidence": conf,
            "source": "auto_detected",
            "selected_by_default": conf == "extremely_high",
            "auto_apply": False,
        })
        add_candidate(candidates, candidate)

    for match in PHONE_RE.finditer(text_str):
        conf = "high" if field_is_phone else "medium"
        reason = "Phone-like value in phone/mobile field" if field_is_phone else "Phone-like value detected"
        candidate = candidate_base(endpoint, location, field_path, match.group(0))
        candidate.update({
            "replacement": "${__Random(7000000000,9999999999,)}",
            "reason": reason,
            "confidence": conf,
            "source": "auto_detected",
            "selected_by_default": conf == "extremely_high",
            "auto_apply": False,
        })
        add_candidate(candidates, candidate)

    return candidates


def inspect_json_value(endpoint: Dict[str, Any], value: Any, location: str, field_path: str, rules: List[Dict[str, Any]]):
    candidates = []
    if isinstance(value, dict):
        for key, child in value.items():
            candidates.extend(inspect_json_value(endpoint, child, location, f"{field_path}.{key}", rules))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            candidates.extend(inspect_json_value(endpoint, child, location, f"{field_path}[{index}]", rules))
    elif isinstance(value, (str, int, float, bool)) or value is None:
        text = str(value) if value is not None else ""
        candidates.extend(detect_rule_candidates(endpoint, text, location, field_path, rules))
        candidates.extend(detect_auto_candidates(endpoint, text, location, field_path))
    return candidates


def inspect_raw_body(endpoint: Dict[str, Any], rules: List[Dict[str, Any]]):
    raw_body = endpoint.get("raw_body") or ""
    candidates = []
    if not raw_body:
        return candidates
    stripped = raw_body.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(raw_body)
            return inspect_json_value(endpoint, parsed, "raw_body", "$", rules)
        except json.JSONDecodeError:
            pass

    xml_text_pattern = re.compile(r"<([A-Za-z_][\w:.-]*)\b[^>]*>([^<]+)</\1>")
    xml_matches = list(xml_text_pattern.finditer(raw_body))
    if xml_matches:
        for match in xml_matches:
            field_path = match.group(1)
            value = match.group(2).strip()
            candidates.extend(detect_rule_candidates(endpoint, value, "raw_body", field_path, rules))
            candidates.extend(detect_auto_candidates(endpoint, value, "raw_body", field_path))
    else:
        candidates.extend(detect_rule_candidates(endpoint, raw_body, "raw_body", "raw_body", rules))
        candidates.extend(detect_auto_candidates(endpoint, raw_body, "raw_body", "raw_body"))
    return candidates


def inspect_full_url(endpoint: Dict[str, Any], rules: List[Dict[str, Any]]):
    candidates = []
    full_url = endpoint.get("full_url") or ""
    if not full_url:
        return candidates
    try:
        parsed = urlparse(full_url)
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            for key, values in params.items():
                for val in values:
                    if has_jmeter_expression(val):
                        continue
                    field_path = f"query.{key}"
                    candidates.extend(detect_rule_candidates(endpoint, val, "full_url", field_path, rules))
                    candidates.extend(detect_auto_candidates(endpoint, val, "full_url", field_path))
    except Exception:
        pass
    return candidates


def analyze_functional_parameterization(endpoints: List[Dict[str, Any]], rules_config: Optional[Dict[str, Any]] = None):
    rules = (rules_config or {}).get("rules", [])
    candidates = []
    for endpoint in endpoints or []:
        candidates.extend(inspect_raw_body(endpoint, rules))
        candidates.extend(inspect_full_url(endpoint, rules))
        for location in ("query_params", "headers", "form_data", "urlencoded", "multipart_files"):
            for item in endpoint.get(location, []) or []:
                field_path = item.get("key") or location
                value = item.get("value")
                if value is None:
                    value = item.get("src")
                if value is None:
                    value = ""
                value = str(value)
                candidates.extend(detect_rule_candidates(endpoint, value, location, field_path, rules))
                candidates.extend(detect_auto_candidates(endpoint, value, location, field_path))
    
    rules_list = [c for c in candidates if c.get("source") == "rule"]
    auto_list = [c for c in candidates if c.get("source") == "auto_detected"]

    rule_keys = {(c.get("request_index"), c.get("location"), c.get("field_path")) for c in rules_list}
    auto_list = [
        c for c in auto_list
        if (c.get("request_index"), c.get("location"), c.get("field_path")) not in rule_keys
    ]

    return rules_list + auto_list


def replace_outside_jmeter_expressions(text: str, original: str, replacement: str):
    if not isinstance(text, str) or not original:
        return text
    parts = JMETER_EXPR_RE.split(text)
    expressions = JMETER_EXPR_RE.findall(text)
    output = []
    for index, part in enumerate(parts):
        output.append(part.replace(original, replacement))
        if index < len(expressions):
            output.append(expressions[index])
    return "".join(output)


def apply_candidate_to_endpoint(endpoint: Dict[str, Any], candidate: Dict[str, Any]):
    original = candidate.get("original_value", "")
    replacement = candidate.get("replacement", "")
    location = candidate.get("location", "")
    if not original or not replacement:
        return

    if location == "raw_body":
        endpoint["raw_body"] = replace_outside_jmeter_expressions(endpoint.get("raw_body", ""), original, replacement)
        return

    if location == "full_url":
        full_url = endpoint.get("full_url", "")
        if original in full_url:
            endpoint["full_url"] = full_url.replace(original, replacement)
        return

    for item in endpoint.get(location, []) or []:
        for key in ("value", "src"):
            if key in item:
                item[key] = replace_outside_jmeter_expressions(item.get(key), original, replacement)


def apply_functional_parameterization(
    endpoints: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    selected_ids: Optional[Set[str]] = None,
    include_auto_apply: bool = True,
):
    applied = []
    by_index = {endpoint.get("source_index", index): endpoint for index, endpoint in enumerate(endpoints or [])}
    
    # Avoid duplicate/conflicting replacements on the same parameter path
    applied_targets = set()
    
    for candidate in candidates or []:
        target_key = (candidate.get("request_index"), candidate.get("location"), candidate.get("field_path"))
        if target_key in applied_targets:
            continue

        # If selected_ids is explicitly provided, only apply selected candidates.
        # Otherwise, fall back to auto_apply check.
        if selected_ids is not None:
            should_apply = candidate.get("id") in selected_ids
        else:
            should_apply = include_auto_apply and candidate.get("auto_apply")

        if not should_apply:
            continue
        endpoint = by_index.get(candidate.get("request_index"))
        if endpoint is None:
            continue
        apply_candidate_to_endpoint(endpoint, candidate)
        applied_targets.add(target_key)
        applied.append(candidate)
    return applied


def clone_and_parameterize(endpoints: List[Dict[str, Any]], candidates: List[Dict[str, Any]], selected_ids: Optional[Set[str]] = None):
    cloned = deepcopy(endpoints)
    applied = apply_functional_parameterization(cloned, candidates, selected_ids)
    return cloned, applied
