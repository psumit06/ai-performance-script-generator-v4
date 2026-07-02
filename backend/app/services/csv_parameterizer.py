from typing import Any, Dict, List


def build_csv_value_mapping(csv_files: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Builds a replacement map from CSV data values to JMeter variables.
    Header names are variable names; every non-empty value under a header maps to ${header}.
    """
    mapping = {}
    for csv_file in csv_files or []:
        for item in csv_file.get("value_mappings", []):
            value = item.get("value")
            variable = item.get("variable")
            if value and variable and value not in mapping:
                mapping[value] = f"${{{variable}}}"
    return mapping


def parameterize_text(text: Any, value_mapping: Dict[str, str]) -> Any:
    if not isinstance(text, str) or not text or not value_mapping:
        return text

    result = text
    for value in sorted(value_mapping, key=len, reverse=True):
        replacement = value_mapping[value]
        if replacement in result:
            continue
        result = result.replace(value, replacement)
    return result


def parameterize_fields(fields: List[Dict[str, Any]], value_mapping: Dict[str, str]):
    for field in fields or []:
        for key in ("value", "src"):
            if key in field:
                field[key] = parameterize_text(field.get(key), value_mapping)


def parameterize_endpoint(endpoint: Dict[str, Any], value_mapping: Dict[str, str]):
    endpoint["full_url"] = parameterize_text(endpoint.get("full_url", ""), value_mapping)
    endpoint["host"] = parameterize_text(endpoint.get("host", ""), value_mapping)
    endpoint["path"] = parameterize_text(endpoint.get("path", ""), value_mapping)
    endpoint["raw_body"] = parameterize_text(endpoint.get("raw_body", ""), value_mapping)

    parameterize_fields(endpoint.get("query_params", []), value_mapping)
    parameterize_fields(endpoint.get("headers", []), value_mapping)
    parameterize_fields(endpoint.get("form_data", []), value_mapping)
    parameterize_fields(endpoint.get("urlencoded", []), value_mapping)
    parameterize_fields(endpoint.get("multipart_files", []), value_mapping)

    graphql = endpoint.get("graphql")
    if isinstance(graphql, dict):
        for key in ("query", "variables"):
            graphql[key] = parameterize_text(graphql.get(key), value_mapping)


def parameterize_endpoints_from_csv(endpoints: List[Dict[str, Any]], csv_files: List[Dict[str, Any]]):
    value_mapping = build_csv_value_mapping(csv_files)
    if not value_mapping:
        return endpoints

    for endpoint in endpoints or []:
        parameterize_endpoint(endpoint, value_mapping)
    return endpoints
