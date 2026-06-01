from app.services.xml_helpers import (
    string_prop,
    bool_prop,
    int_prop
)


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

{int_prop(
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


def build_csv_dataset():

    return f"""
<CSVDataSet guiclass="TestBeanGUI"
testclass="CSVDataSet"
testname="CSV User Data"
enabled="true">

{string_prop("filename", "users.csv")}

{string_prop("variableNames", "username,password")}

{string_prop("delimiter", ",")}

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
