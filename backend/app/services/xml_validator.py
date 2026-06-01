import xml.etree.ElementTree as ET


def validate_xml(xml_content):

    try:

        ET.fromstring(xml_content)

        return {
            "valid": True,
            "error": None
        }

    except Exception as e:

        return {
            "valid": False,
            "error": str(e)
        }