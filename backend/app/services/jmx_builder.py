from app.services.jmeter_components import (
    build_test_plan,
    build_thread_group,
    build_cookie_manager,
    build_transaction_controller,
    build_csv_dataset
)
from app.services.xml_helpers import (
    string_prop,
    bool_prop,
    escape_xml
)
from app.services.http_argument_builder import (
    build_http_argument
)

def split_variable_host_path(host, path, full_url):
    """
    Keeps JMeter variable hosts in the server-name field instead of the path.
    Example: ${c_host}/booking -> domain=${c_host}, path=/booking
    """
    candidate = path or full_url or ""
    if host or not candidate.startswith("${"):
        return host, path

    closing = candidate.find("}")
    if closing == -1:
        return host, path

    variable_host = candidate[:closing + 1]
    suffix = candidate[closing + 1:] or "/"
    if suffix.startswith("?"):
        suffix = "/" + suffix
    elif not suffix.startswith("/"):
        suffix = "/" + suffix

    return variable_host, suffix

def render_extractor(ext):
    """
    Renders the exact JMeter Post-Processor element depending on type.
    """
    t = ext.get("type")
    var_name = ext.get("var_name", "c_token")
    
    if t == "json_extractor":
        return f"""
<JSONPostProcessor guiclass="JSONPostProcessorGui"
testclass="JSONPostProcessor"
testname="JSON Extractor - {var_name}"
enabled="true">

<stringProp name="JSONPostProcessor.referenceNames">{var_name}</stringProp>
<stringProp name="JSONPostProcessor.jsonPathExprs">{ext.get('json_path', '$.token')}</stringProp>
<stringProp name="JSONPostProcessor.match_numbers">1</stringProp>
<stringProp name="JSONPostProcessor.defaultValues">NOT_FOUND</stringProp>

</JSONPostProcessor>
<hashTree/>
"""
    elif t == "boundary_extractor":
        left_b = escape_xml(ext.get("left_boundary", ""))
        right_b = escape_xml(ext.get("right_boundary", ""))
        return f"""
<BoundaryExtractor guiclass="BoundaryExtractorGui"
testclass="BoundaryExtractor"
testname="Boundary Extractor - {var_name}"
enabled="true">

{bool_prop("BoundaryExtractor.useHeaders", False)}
<stringProp name="BoundaryExtractor.refname">{var_name}</stringProp>
<stringProp name="BoundaryExtractor.lboundary">{left_b}</stringProp>
<stringProp name="BoundaryExtractor.rboundary">{right_b}</stringProp>
<stringProp name="BoundaryExtractor.match_number">1</stringProp>
<stringProp name="BoundaryExtractor.default">NOT_FOUND</stringProp>

</BoundaryExtractor>
<hashTree/>
"""
    elif t == "regex_extractor":
        regex_val = escape_xml(ext.get("regex", ""))
        return f"""
<RegexExtractor guiclass="RegexExtractorGui"
testclass="RegexExtractor"
testname="Regex Extractor - {var_name}"
enabled="true">

{bool_prop("RegexExtractor.useHeaders", False)}
<stringProp name="RegexExtractor.refname">{var_name}</stringProp>
<stringProp name="RegexExtractor.regex">{regex_val}</stringProp>
<stringProp name="RegexExtractor.template">$1$</stringProp>
<stringProp name="RegexExtractor.default">NOT_FOUND</stringProp>
<stringProp name="RegexExtractor.match_number">1</stringProp>

</RegexExtractor>
<hashTree/>
"""
    elif t == "header_extractor":
        regex_val = escape_xml(ext.get("regex", ""))
        return f"""
<RegexExtractor guiclass="RegexExtractorGui"
testclass="RegexExtractor"
testname="Header Extractor - {var_name}"
enabled="true">

{bool_prop("RegexExtractor.useHeaders", True)}
<stringProp name="RegexExtractor.refname">{var_name}</stringProp>
<stringProp name="RegexExtractor.regex">{regex_val}</stringProp>
<stringProp name="RegexExtractor.template">$1$</stringProp>
<stringProp name="RegexExtractor.default">NOT_FOUND</stringProp>
<stringProp name="RegexExtractor.match_number">1</stringProp>

</RegexExtractor>
<hashTree/>
"""
    return ""

def build_http_file_arg(field_name, file_path, mime_type="application/octet-stream"):
    """
    Renders an HTTPFileArg element for multipart file uploads in JMeter.
    """
    return f"""
<elementProp name="" elementType="HTTPFileArg">

{string_prop("HTTPSampler.fileName", file_path)}

{string_prop("HTTPSampler.paramName", field_name)}

{string_prop("HTTPSampler.mimeType", mime_type)}

</elementProp>
"""

def render_sampler(request):
    """
    Renders a single HTTPSamplerProxy element and its headers/extractors/timers.
    """
    protocol = request.get("protocol", "http")
    host = request.get("host", "")
    port = request.get("port", "")
    path = request.get("path", "/")
    method = request.get("method", "GET")
    headers = request.get("headers", [])
    query_params = request.get("query_params", [])
    body_mode = request.get("body_mode", "")
    raw_body = request.get("raw_body", "")
    form_data = request.get("form_data", [])
    urlencoded = request.get("urlencoded", [])
    content_type = request.get("content_type", "")
    multipart_files = request.get("multipart_files", [])

    if not host and request.get("full_url"):
        path = request.get("full_url")

    host, path = split_variable_host_path(host, path, request.get("full_url", ""))
    
    xml = f"""
<HTTPSamplerProxy guiclass="HttpTestSampleGui"
testclass="HTTPSamplerProxy"
testname="{escape_xml(request['name'])}"
enabled="true">

<elementProp name="HTTPsampler.Arguments"
elementType="Arguments">

<collectionProp name="Arguments.arguments">
"""

    # Query Params
    for param in query_params:
        xml += build_http_argument(param.get("key", ""), param.get("value", ""))

    # Form Data body (text fields only - files go in separate collection)
    if body_mode == "formdata":
        for item in form_data:
            xml += build_http_argument(item.get("key", ""), item.get("value", ""))
            
    # Raw JSON/XML body
    elif body_mode == "raw" or "json" in content_type.lower():
        xml += f"""
<elementProp name=""
elementType="HTTPArgument">

{bool_prop("HTTPArgument.always_encode", False)}

{string_prop("Argument.value", raw_body)}

{string_prop("Argument.metadata", "=")}

</elementProp>
"""
    # Urlencoded body
    elif body_mode == "urlencoded":
        for item in urlencoded:
            xml += build_http_argument(item.get("key", ""), item.get("value", ""))

    xml += """
</collectionProp>

</elementProp>
"""

    # File uploads go in a SEPARATE collection (JMeter requires this)
    if multipart_files:
        xml += """
<collectionProp name="HTTPSampler.files">
"""
        for file_item in multipart_files:
            xml += build_http_file_arg(
                file_item.get("key", ""),
                file_item.get("src", "")
            )
        xml += """
</collectionProp>
"""

    # Sampler host/port settings
    xml += f"""
{string_prop("HTTPSampler.domain", host)}

{string_prop("HTTPSampler.port", port)}

{string_prop("HTTPSampler.protocol", protocol)}

{string_prop("HTTPSampler.path", path)}

{string_prop("HTTPSampler.method", method)}

{bool_prop("HTTPSampler.follow_redirects", True)}

{bool_prop("HTTPSampler.auto_redirects", False)}

{bool_prop("HTTPSampler.use_keepalive", True)}

{bool_prop("HTTPSampler.DO_MULTIPART_POST", body_mode == "formdata")}

{bool_prop("HTTPSampler.monitor", False)}

{string_prop("HTTPSampler.embedded_url_re", "")}
"""

    # Body raw flag
    if body_mode == "raw" or "json" in content_type.lower():
        xml += f"{bool_prop('HTTPSampler.postBodyRaw', True)}\n"
    else:
        xml += f"{bool_prop('HTTPSampler.postBodyRaw', False)}\n"

    xml += """
</HTTPSamplerProxy>

<hashTree>
"""

    # Render Header Manager if headers present (or if we need to add Content-Type)
    has_content_type = any(h.get("key", "").lower() == "content-type" for h in headers)
    needs_content_type = not has_content_type and body_mode in ("urlencoded", "formdata", "raw")
    
    if headers or needs_content_type:
        xml += """
<HeaderManager guiclass="HeaderPanel"
testclass="HeaderManager"
testname="HTTP Header Manager"
enabled="true">

<collectionProp name="HeaderManager.headers">
"""
        ignored_headers = ["content-length", "host", "postman-token", "connection", "accept-encoding"]
        for header in headers:
            key = header.get("key", "")
            value = header.get("value", "")
            if key.lower() in ignored_headers:
                continue
                
            xml += f"""
<elementProp name=""
elementType="Header">

{string_prop("Header.name", key)}

{string_prop("Header.value", value)}

</elementProp>
"""
        
        # Auto-add Content-Type based on body mode if not already present
        if needs_content_type:
            if body_mode == "urlencoded":
                ct_value = "application/x-www-form-urlencoded"
            elif body_mode == "formdata":
                ct_value = "multipart/form-data"
            elif body_mode == "raw":
                # Default to JSON for raw bodies
                ct_value = "application/json"
            else:
                ct_value = ""
            
            if ct_value:
                xml += f"""
<elementProp name=""
elementType="Header">

{string_prop("Header.name", "Content-Type")}

{string_prop("Header.value", ct_value)}

</elementProp>
"""
        
        xml += """
</collectionProp>

</HeaderManager>

<hashTree/>
"""

    # Render Extractors
    for ext in request.get("extractors", []):
        xml += render_extractor(ext)

    # Close Sampler Hash Tree
    xml += "</hashTree>\n"
    return xml

def render_flow_control_action(name, delay_ms):
    delay_ms = max(0, int(delay_ms))
    safe_name = escape_xml(name)
    return f"""
<TestAction guiclass="TestActionGui"
testclass="TestAction"
testname="{safe_name}"
enabled="true">

<intProp name="ActionProcessor.action">1</intProp>
<intProp name="ActionProcessor.target">0</intProp>
<stringProp name="ActionProcessor.duration">{delay_ms}</stringProp>

</TestAction>
<hashTree/>
"""

def render_think_time_action(delay_ms):
    return render_flow_control_action("Think Time", delay_ms)

def render_pacing_action(delay_ms):
    return render_flow_control_action("Pacing", delay_ms)

def render_result_collector(name, guiclass):
    safe_name = escape_xml(name)
    return f"""
<ResultCollector guiclass="{guiclass}"
testclass="ResultCollector"
testname="{safe_name}"
enabled="false">

<boolProp name="ResultCollector.error_logging">false</boolProp>

<objProp>
<name>saveConfig</name>
<value class="SampleSaveConfiguration">
<time>true</time>
<latency>true</latency>
<timestamp>true</timestamp>
<success>true</success>
<label>true</label>
<code>true</code>
<message>true</message>
<threadName>true</threadName>
<dataType>true</dataType>
<encoding>false</encoding>
<assertions>true</assertions>
<subresults>true</subresults>
<responseData>false</responseData>
<samplerData>false</samplerData>
<xml>false</xml>
<fieldNames>true</fieldNames>
<responseHeaders>false</responseHeaders>
<requestHeaders>false</requestHeaders>
<responseDataOnError>false</responseDataOnError>
<saveAssertionResultsFailureMessage>true</saveAssertionResultsFailureMessage>
<assertionsResultsToSave>0</assertionsResultsToSave>
<bytes>true</bytes>
<sentBytes>true</sentBytes>
<url>true</url>
<threadCounts>true</threadCounts>
<idleTime>true</idleTime>
<connectTime>true</connectTime>
</value>
</objProp>

<stringProp name="filename"></stringProp>

</ResultCollector>
<hashTree/>
"""

def render_disabled_listeners():
    return (
        render_result_collector("View Results Tree", "ViewResultsFullVisualizer")
        + render_result_collector("Aggregate Report", "StatVisualizer")
    )

def build_jmx(test_plan):
    users = test_plan["thread_group"]["users"]
    ramp_up = test_plan["thread_group"]["ramp_up"]
    duration = test_plan["thread_group"]["duration"]
    loops = test_plan["thread_group"].get("loops", -1)
    scheduler = test_plan["thread_group"].get("scheduler", True)
    pacing = int(test_plan["thread_group"].get("pacing", 0) or 0)
    flow = test_plan.get("flow", [])
    exclusion_regex = test_plan.get("exclusion_regex", "")
    csv_files = test_plan.get("csv_files", [])

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2"
properties="5.0"
jmeter="5.6.3">

<hashTree>
"""

    # 1. Test Plan node
    xml += build_test_plan()
    xml += "<hashTree>"

    # 2. Thread Group node
    xml += build_thread_group(users, ramp_up, duration, loops=loops, scheduler=scheduler)
    xml += "<hashTree>"

    # 3. Cookie Manager
    xml += build_cookie_manager()
    xml += "<hashTree/>"

    # 3.5. CSV Data Set Config elements (if any CSV files uploaded)
    for csv_file in csv_files:
        filename = csv_file.get("filename", "")
        variables = csv_file.get("variables", [])
        delimiter = csv_file.get("delimiter", ",")
        if filename and variables:
            xml += build_csv_dataset(filename, variables, delimiter)
            xml += "<hashTree/>"

    # 4. HTTP Request Defaults with Generated URL exclusions
    xml += f"""
<ConfigTestElement guiclass="HttpDefaultsGui"
testclass="ConfigTestElement"
testname="HTTP Request Defaults"
enabled="true">

<elementProp name="HTTPsampler.Arguments"
elementType="Arguments"
guiclass="HTTPArgumentsPanel"
testclass="Arguments"
testname="User Defined Variables"
enabled="true">

<collectionProp name="Arguments.arguments"/>

</elementProp>

{string_prop("HTTPSampler.domain", "")}
{string_prop("HTTPSampler.port", "")}
{string_prop("HTTPSampler.protocol", "")}
{string_prop("HTTPSampler.contentEncoding", "")}
{string_prop("HTTPSampler.path", "")}
{string_prop("HTTPSampler.embedded_url_re", exclusion_regex)}
{string_prop("HTTPSampler.concurrentPool", "6")}

</ConfigTestElement>
<hashTree/>
"""

    # 5. Render Logical Flow (Transaction Controllers, Parallel Controllers, timers)
    for tx_index, tx in enumerate(flow):
        tx_name = tx["transaction_name"]
        groups = tx["groups"]
        think_time = tx.get("think_time", 0)

        # RENDER TRANSACTION CONTROLLER
        xml += build_transaction_controller(tx_name)
        xml += "<hashTree>\n"

        for group in groups:
            if len(group) > 1:
                # RENDER PARALLEL CONTROLLER
                xml += """
<com.blazemeter.jmeter.controller.ParallelSampler
guiclass="com.blazemeter.jmeter.controller.ParallelControllerGui"
testclass="com.blazemeter.jmeter.controller.ParallelSampler"
testname="Parallel Resources"
enabled="true">

<boolProp name="PARENT_SAMPLE">true</boolProp>

</com.blazemeter.jmeter.controller.ParallelSampler>

<hashTree>
"""
                for request in group:
                    xml += render_sampler(request)
                    
                # Close Parallel Controller Hash Tree
                xml += "</hashTree>\n"
            else:
                # Render single sampler normally
                xml += render_sampler(group[0])

        # RENDER THINK TIME AS FLOW CONTROL ACTION (skip for last transaction)
        is_last_tx = tx_index == len(flow) - 1
        if not is_last_tx and think_time > 300:
            xml += render_think_time_action(think_time)

        # RENDER PACING AT THE END OF THE LAST TRANSACTION CONTROLLER
        if is_last_tx and pacing > 300:
            xml += render_pacing_action(pacing)

        # Close Transaction Controller Hash Tree
        xml += "</hashTree>\n"

    # Disabled debug/report listeners are included for local inspection only.
    xml += render_disabled_listeners()

    # Close Thread Group
    xml += "</hashTree>\n"
    # Close Test Plan
    xml += "</hashTree>\n"
    # Close Root Test Plan tag
    xml += "</hashTree>\n</jmeterTestPlan>\n"
    
    return xml
