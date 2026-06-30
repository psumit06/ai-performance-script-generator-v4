import os
from lxml import etree

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schemas")
XSD_PATH = os.path.join(SCHEMA_DIR, "jmeter-schema.xsd")


def _load_schema():
    """Load and compile the JMeter XSD schema (cached)."""
    if not hasattr(_load_schema, "_compiled"):
        xsd_doc = etree.parse(XSD_PATH)
        _load_schema._compiled = etree.XMLSchema(xsd_doc)
    return _load_schema._compiled


def validate_xml(xml_content):
    """Basic well-formedness check using lxml."""
    try:
        etree.fromstring(xml_content.encode("utf-8"))
        return {"valid": True, "error": None}
    except etree.XMLSyntaxError as e:
        return {"valid": False, "error": str(e)}


def validate_jmx_xsd(xml_content):
    """
    Validate JMX XML against the JMeter XSD schema.
    Returns:
        {
            "valid": True/False,
            "errors": [{"line": int, "column": int, "message": str}, ...]
        }
    """
    try:
        xml_doc = etree.fromstring(xml_content.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        return {
            "valid": False,
            "errors": [{"line": getattr(e, "lineno", 0), "column": getattr(e, "colno", 0), "message": str(e)}]
        }

    try:
        schema = _load_schema()
    except Exception as e:
        return {
            "valid": False,
            "errors": [{"line": 0, "column": 0, "message": f"Failed to load XSD schema: {e}"}]
        }

    is_valid = schema.validate(xml_doc)
    errors = []
    if not is_valid:
        for error in schema.error_log:
            errors.append({
                "line": error.line,
                "column": error.column,
                "message": error.message,
            })

    return {
        "valid": is_valid,
        "errors": errors,
    }


def validate_jmx_xsd_file(jmx_path):
    """Validate a JMX file on disk against the XSD schema."""
    with open(jmx_path, "r", encoding="utf-8") as f:
        content = f.read()
    return validate_jmx_xsd(content)
