import json


def detect_format(raw_content):

    data = json.loads(raw_content)

    # Postman
    if "item" in data:
        return "postman"

    # HAR
    if "log" in data:
        return "har"

    return "unknown"