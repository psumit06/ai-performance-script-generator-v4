import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set


UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
TIMESTAMP_14_RE = re.compile(r"\b(20\d{12})\b")
TIMESTAMP_12_RE = re.compile(r"\b(20\d{10})\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b[6-9]\d{9}\b")
JMETER_EXPR_RE = re.compile(r"\$\{[^}]+\}")


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
        "replacement",
        "source",
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
        return bool(TIMESTAMP_14_RE.search(value))
    if pattern == "timestamp_12":
        return bool(TIMESTAMP_12_RE.search(value))
    return False


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
            matches = [match.group(0) for match in re.finditer(value_regex, text or "")]
        elif value_pattern and value_matches(text or "", value_pattern):
            match = re.search(UUID_RE if value_pattern == "uuid" else re.escape(text), text or "")
            matches = [match.group(0)] if match else [text]
        elif not value_pattern:
            matches = [text]

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
    if not text or has_jmeter_expression(text):
        return candidates

    lower_field = (field_path or "").lower()
    for match in UUID_RE.finditer(text):
        if any(token in lower_field for token in ("id", "uuid", "guid", "interaction", "correlation", "trace")):
            candidate = candidate_base(endpoint, location, field_path, match.group(0))
            candidate.update({
                "replacement": "${__UUID()}",
                "reason": "UUID-like value in ID/correlation field",
                "confidence": "high",
                "source": "auto_detected",
                "selected_by_default": False,
                "auto_apply": False,
            })
            add_candidate(candidates, candidate)

    if any(token in lower_field for token in ("timestamp", "datetime", "date", "time")):
        for regex, replacement, reason in (
            (TIMESTAMP_14_RE, "${__time(yyyyMMddHHmmss,)}", "14-digit timestamp-like value"),
            (TIMESTAMP_12_RE, "${__time(yyyyMMddHHmm,)}", "12-digit timestamp-like value"),
        ):
            for match in regex.finditer(text):
                candidate = candidate_base(endpoint, location, field_path, match.group(1))
                candidate.update({
                    "replacement": replacement,
                    "reason": reason,
                    "confidence": "medium",
                    "source": "auto_detected",
                    "selected_by_default": False,
                    "auto_apply": False,
                })
                add_candidate(candidates, candidate)

    if "email" in lower_field:
        for match in EMAIL_RE.finditer(text):
            candidate = candidate_base(endpoint, location, field_path, match.group(0))
            candidate.update({
                "replacement": "user_${__threadNum}_${__time()}@test.com",
                "reason": "Email-like value in email field",
                "confidence": "medium",
                "source": "auto_detected",
                "selected_by_default": False,
                "auto_apply": False,
            })
            add_candidate(candidates, candidate)

    if any(token in lower_field for token in ("phone", "mobile")):
        for match in PHONE_RE.finditer(text):
            candidate = candidate_base(endpoint, location, field_path, match.group(0))
            candidate.update({
                "replacement": "${__Random(7000000000,9999999999,)}",
                "reason": "Phone-like value in phone/mobile field",
                "confidence": "medium",
                "source": "auto_detected",
                "selected_by_default": False,
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
    elif isinstance(value, (str, int, float)):
        text = str(value)
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
    for match in xml_text_pattern.finditer(raw_body):
        field_path = match.group(1)
        value = match.group(2).strip()
        candidates.extend(detect_rule_candidates(endpoint, value, "raw_body", field_path, rules))
        candidates.extend(detect_auto_candidates(endpoint, value, "raw_body", field_path))

    candidates.extend(detect_rule_candidates(endpoint, raw_body, "raw_body", "raw_body", rules))
    return candidates


def analyze_functional_parameterization(endpoints: List[Dict[str, Any]], rules_config: Optional[Dict[str, Any]] = None):
    rules = (rules_config or {}).get("rules", [])
    candidates = []
    for endpoint in endpoints or []:
        candidates.extend(inspect_raw_body(endpoint, rules))
        for location in ("query_params", "headers", "form_data", "urlencoded", "multipart_files"):
            for item in endpoint.get(location, []) or []:
                field_path = item.get("key") or location
                value = item.get("value") or item.get("src") or ""
                candidates.extend(detect_rule_candidates(endpoint, value, location, field_path, rules))
                candidates.extend(detect_auto_candidates(endpoint, value, location, field_path))
    return candidates


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
    selected_ids = selected_ids or set()
    applied = []
    by_index = {endpoint.get("source_index", index): endpoint for index, endpoint in enumerate(endpoints or [])}
    for candidate in candidates or []:
        should_apply = candidate.get("id") in selected_ids or (include_auto_apply and candidate.get("auto_apply"))
        if not should_apply:
            continue
        endpoint = by_index.get(candidate.get("request_index"))
        if endpoint is None:
            continue
        apply_candidate_to_endpoint(endpoint, candidate)
        applied.append(candidate)
    return applied


def clone_and_parameterize(endpoints: List[Dict[str, Any]], candidates: List[Dict[str, Any]], selected_ids: Optional[Set[str]] = None):
    cloned = deepcopy(endpoints)
    applied = apply_functional_parameterization(cloned, candidates, selected_ids)
    return cloned, applied
