import json
from app.services.format_detector import detect_format
from app.services.postman_parser import parse_postman_collection
from app.services.har_parser import parse_har

def parse_api_spec(content):
    fmt = detect_format(content)
    if fmt == "postman":
        return parse_postman_collection(content)
    elif fmt == "har":
        return parse_har(content)
    else:
        raise Exception("Unsupported API specification format: Could not determine if Postman Collection or HTTP Archive (HAR).")