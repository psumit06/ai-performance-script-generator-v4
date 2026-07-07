from typing import List
from app.services.xml_helpers import (
    string_prop,
    bool_prop
)


def _arg_element(name, value):
    return (
        f'<elementProp name="{name}" elementType="Argument">\n'
        f'{string_prop("Argument.name", name)}'
        f'{string_prop("Argument.value", value)}'
        f'{string_prop("Argument.metadata", "=")}'
        f'</elementProp>\n'
    )


UDV_VARIABLES = [
    ("Datapath", "${__P(datadir)}"),
    ("ThinkTime", "${__P(thinktime)}"),
    ("TEST_ID", "${__time(yyyy-MM-dd'T'hh:mm:ss)}"),
    ("Duration", "${__P(duration)}"),
    ("starttime", "${__time(,)}"),
    ("RelVsn", "${__P(Release)}"),
    ("hold", "${__P(delayaftertest)}"),
    ("TestFolderName", "${__P(DateTime,)}"),
]


def build_test_plan():

    xml = ""

    xml += """
<TestPlan guiclass="TestPlanGui"
testclass="TestPlan"
testname="AI Generated Test Plan"
enabled="true">
"""

    xml += string_prop(
        "TestPlan.comments",
        ""
    )

    xml += bool_prop(
        "TestPlan.functional_mode",
        False
    )

    xml += bool_prop(
        "TestPlan.serialize_threadgroups",
        False
    )

    xml += """
<elementProp name="TestPlan.user_defined_variables" elementType="Arguments" guiclass="ArgumentsPanel" testclass="Arguments" testname="User Defined Variables" enabled="true">
<collectionProp name="Arguments.arguments"/>
</elementProp>
"""

    xml += bool_prop(
        "TestPlan.tearDown_on_shutdown",
        True
    )

    xml += "</TestPlan>"

    return xml


def build_thread_group(
    users,
    ramp_up,
    duration,
    loops=-1,
    scheduler=True
):

    return f"""
<ThreadGroup guiclass="ThreadGroupGui"
testclass="ThreadGroup"
testname="Thread Group"
enabled="true">

{string_prop("ThreadGroup.on_sample_error", "continue")}

<elementProp name="ThreadGroup.main_controller"
elementType="LoopController"
guiclass="LoopControlPanel"
testclass="LoopController"
testname="Loop Controller"
enabled="true">

{bool_prop(
    "LoopController.continue_forever",
    False
)}

{string_prop(
    "LoopController.loops",
    loops
)}

</elementProp>

{string_prop(
    "ThreadGroup.num_threads",
    users
)}

{string_prop(
    "ThreadGroup.ramp_time",
    ramp_up
)}

{bool_prop(
    "ThreadGroup.scheduler",
    scheduler
)}

{string_prop(
    "ThreadGroup.duration",
    duration
)}

{string_prop(
    "ThreadGroup.delay",
    0
)}

</ThreadGroup>
"""

def build_cookie_manager():

    return f"""
<CookieManager guiclass="CookiePanel"
testclass="CookieManager"
testname="HTTP Cookie Manager"
enabled="true">

<collectionProp name="CookieManager.cookies"/>

{bool_prop("CookieManager.clearEachIteration", False)}

</CookieManager>
"""


UDV_VARIABLES = [
    ("Datapath", "${__P(datadir)}"),
    ("TEST_ID", "${__time(yyyy-MM-dd'T'hh:mm:ss)}"),
    ("Duration", "${__P(duration)}"),
    ("starttime", "${__time(,)}"),
    ("RelVsn", "${__P(Release)}"),
    ("hold", "${__P(delayaftertest)}"),
    ("TestFolderName", "${__P(DateTime,)}"),
]


def build_user_defined_variables(think_time_ms=0, pacing_ms=0):
    extra = []
    if think_time_ms:
        extra.append(("ThinkTime", str(think_time_ms)))
    if pacing_ms:
        extra.append(("Pacing", str(pacing_ms)))

    all_vars = UDV_VARIABLES + extra

    xml = """
<Arguments guiclass="ArgumentsPanel"
testclass="Arguments"
testname="User Defined Variables"
enabled="true">

<collectionProp name="Arguments.arguments">
"""
    for var_name, var_value in all_vars:
        xml += (
            f'<elementProp name="{var_name}" elementType="Argument">\n'
            f'{string_prop("Argument.name", var_name)}'
            f'{string_prop("Argument.value", var_value)}'
            f'{string_prop("Argument.metadata", "=")}'
            f'</elementProp>\n'
        )
    xml += """</collectionProp>

</Arguments>
"""
    return xml


def build_csv_dataset(filename: str, variable_names: List[str], delimiter: str = ","):
    """
    Build a CSV Data Set Config element for JMeter.
    
    Args:
        filename: Name of the CSV file (will be prefixed with ${Datapath}/)
        variable_names: List of variable names from CSV headers
        delimiter: CSV delimiter character
        
    Returns:
        JMX XML string for CSV Data Set Config
    """
    # Build the full path using JMeter variable ${Datapath}
    csv_path = f"${{Datapath}}/{filename}"
    
    # Join variable names with comma
    variables_str = ",".join(variable_names)
    
    return f"""
<CSVDataSet guiclass="TestBeanGUI"
testclass="CSVDataSet"
testname="CSV Data - {filename}"
enabled="true">

{string_prop("filename", csv_path)}

{string_prop("variableNames", variables_str)}

{string_prop("delimiter", delimiter)}

{bool_prop("ignoreFirstLine", True)}

{bool_prop("quotedData", False)}

{bool_prop("recycle", True)}

{bool_prop("stopThread", False)}

{string_prop("shareMode", "shareMode.all")}

</CSVDataSet>
"""

def build_transaction_controller(name):

    return f"""
<TransactionController guiclass="TransactionControllerGui"
testclass="TransactionController"
testname="{name}"
enabled="true">

{bool_prop("TransactionController.includeTimers", False)}

{bool_prop("TransactionController.parent", False)}

</TransactionController>
"""

def build_throughput_controller(percent):

    return f"""
<ThroughputController guiclass="ThroughputControllerGui"
testclass="ThroughputController"
testname="Throughput Controller"
enabled="true">

<intProp name="ThroughputController.style">1</intProp>

{bool_prop("ThroughputController.perThread", False)}

{string_prop("ThroughputController.percentThroughput", percent)}

</ThroughputController>
"""


def build_jsr223_element(element_type, script, name="Groovy Script", language="groovy"):
    """
    Renders a JSR223 element for JMeter.

    Args:
        element_type: One of "sampler", "pre_processor", "post_processor"
        script: The Groovy script content
        name: Testname attribute for the element
        language: Script language (default "groovy")

    Returns:
        JMX XML string for the JSR223 element with its hashTree
    """
    from app.services.xml_helpers import escape_xml

    safe_name = escape_xml(name)
    safe_script = escape_xml(script)

    tag_map = {
        "sampler": "JSR223Sampler",
        "pre_processor": "JSR223PreProcessor",
        "post_processor": "JSR223PostProcessor",
    }
    tag = tag_map.get(element_type, "JSR223Sampler")

    return f"""
<{tag} guiclass="TestBeanGUI"
testclass="{tag}"
testname="{safe_name}"
enabled="true">

<stringProp name="cacheKey">true</stringProp>

<stringProp name="filename"></stringProp>

<stringProp name="parameters"></stringProp>

<stringProp name="scriptLanguage">{language}</stringProp>

<stringProp name="scriptData">{safe_script}</stringProp>

</{tag}>

<hashTree/>
"""
