from app.services.xml_helpers import (
    string_prop,
    bool_prop
)


def build_http_argument(
    name,
    value,
    always_encode=True
):

    return f"""
<elementProp name="{name}"
elementType="HTTPArgument">

{bool_prop(
    "HTTPArgument.always_encode",
    always_encode
)}

{string_prop(
    "Argument.name",
    name
)}

{string_prop(
    "Argument.value",
    value
)}

{bool_prop(
    "HTTPArgument.use_equals",
    True
)}

{string_prop(
    "Argument.metadata",
    "="
)}

</elementProp>
"""