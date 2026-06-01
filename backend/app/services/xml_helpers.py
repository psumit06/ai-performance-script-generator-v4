import html


def escape_xml(value):

    if value is None:

        return ""

    return html.escape(
        str(value)
    )


def string_prop(name, value):

    escaped_value = escape_xml(value)

    return f'<stringProp name="{name}">{escaped_value}</stringProp>\n'


def bool_prop(name, value):

    bool_value = str(value).lower()

    return f'<boolProp name="{name}">{bool_value}</boolProp>\n'


def int_prop(name, value):

    return f'<intProp name="{name}">{int(value)}</intProp>\n'
