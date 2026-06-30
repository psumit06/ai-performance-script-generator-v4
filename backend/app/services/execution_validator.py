import os
import subprocess
import csv
import shutil
import xml.etree.ElementTree as ET
from app.services.xml_validator import validate_jmx_xsd_file

def get_jmeter_path():
    """
    Get JMeter binary path from environment or common locations.
    Returns platform-appropriate path.
    """
    # Check environment variable first
    jmeter_path = os.getenv("JMETER_BIN")
    if jmeter_path:
        return jmeter_path
    
    # Common installation paths
    common_paths = [
        # Windows
        r"C:\apache-jmeter-5.3\bin\jmeter.bat",
        r"C:\apache-jmeter-5.6.3\bin\jmeter.bat",
        r"C:\Program Files\apache-jmeter\bin\jmeter.bat",
        # Linux/Mac
        "/usr/local/bin/jmeter",
        "/opt/jmeter/bin/jmeter",
        os.path.expanduser("~/jmeter/bin/jmeter"),
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    # Try to find in PATH
    jmeter_in_path = shutil.which("jmeter")
    if jmeter_in_path:
        return jmeter_in_path
    
    # Default fallback (will show helpful error if not found)
    import platform
    if platform.system() == "Windows":
        return r"C:\apache-jmeter-5.3\bin\jmeter.bat"
    else:
        return "/usr/local/bin/jmeter"


def run_jmeter(jmx_path):
    """
    Executes a dry-run iteration of the JMeter script in headless mode,
    clearing previous results first, and parses the JTL results file.
    """
    jmeter_path = get_jmeter_path()
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    output_dir = os.path.join(base_dir, "output")
    jtl_path = os.path.join(output_dir, "results.jtl")
    log_path = os.path.join(base_dir, "jmeter.log")

    xml_report = validate_jmx_xml(jmx_path)
    if not xml_report["valid"]:
        return {
            **xml_report,
            "xml_success_rate": 0.0,
        }

    if not os.path.exists(jmeter_path) and not shutil.which(jmeter_path):
        return {
            **xml_report,
            "valid": False,
            "success_rate": None,
            "xml_success_rate": 100.0,
            "dry_run_skipped": True,
            "jmeter_executed": False,
            "xml_validation_passed": True,
            "skip_reason": f"JMeter binary not found at {jmeter_path}. XML structure validation passed.",
            "failures": [{
                "sampler_label": "JMeter execution skipped",
                "url": "",
                "response_code": "JMETER_NOT_FOUND",
                "response_message": "JMeter binary was not found",
                "failure_message": f"Set JMETER_BIN to a valid jmeter.bat path. XML validation passed for {jmx_path}.",
                "elapsed": "0"
            }]
        }

    # 1. Clean up old result files (JMeter refuses to overwrite JTL by default)
    if os.path.exists(jtl_path):
        try:
            os.remove(jtl_path)
        except Exception as e:
            print(f"Failed to clear old JTL: {e}")
            
    if os.path.exists(log_path):
        try:
            os.remove(log_path)
        except Exception:
            pass

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # 2. Build and run command
    # We run 1 loop, 1 user using the JMX script
    # Increased timeout to handle slower environments and network latency
    timeout_seconds = int(os.getenv("JMETER_TIMEOUT_SECONDS", "120"))
    try:
        print(f"#####Running JMeter dry-run: {jmeter_path} -n -t {jmx_path} -l {jtl_path} -j {log_path}")
        # Run JMeter with connection timeout settings to prevent hanging
        result = subprocess.run(
            [jmeter_path, "-n", "-t", jmx_path, "-l", jtl_path, "-j", log_path,
             "-Jjmeterengine.force.system.exit=true",
             "-Jsocket.connect.timeout=5000"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired as exc:
        # Try to read JMeter log for more details about the timeout
        log_errors = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    for line in lines[-20:]:
                        if "ERROR" in line or "Exception" in line or "timeout" in line.lower():
                            log_errors.append(line.strip())
            except Exception:
                pass
        
        # Kill any remaining JMeter process
        try:
            import signal
            if hasattr(signal, 'SIGTERM'):
                os.killpg(os.getpgid(result.pid), signal.SIGTERM)
        except Exception:
            pass
        
        return {
            "valid": False,
            "success_rate": 0.0,
            "xml_success_rate": 100.0,
            "total_requests": 0,
            "failed_requests": 1,
            "failures": [{
                "sampler_label": "JMeter dry-run timeout",
                "url": "",
                "response_code": "TIMEOUT",
                "response_message": f"JMeter exceeded {timeout_seconds}s dry-run timeout. The server may be unreachable or responding slowly.",
                "failure_message": (exc.stderr or exc.stdout or "").strip() if isinstance(exc.stderr or exc.stdout, str) else "",
                "elapsed": str(timeout_seconds * 1000)
            }],
            "log_errors": log_errors or [f"JMeter dry-run exceeded {timeout_seconds}s timeout."],
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "dry_run_skipped": False,
            "jmeter_executed": True,
            "xml_validation_passed": True,
            "jmeter_command": f"{jmeter_path} -n -t {jmx_path} -l {jtl_path} -j {log_path}",
            "jtl_path": jtl_path,
            "log_path": log_path,
            "skip_reason": ""
        }

    failures = []
    success_rate = 100.0
    total_requests = 0
    failed_requests = 0

    # 3. Parse JTL file if created
    if os.path.exists(jtl_path):
        try:
            with open(jtl_path, mode="r", encoding="utf-8", errors="ignore") as f:
                # Detect separator (standard is comma or tab)
                sample_line = f.readline()
                f.seek(0)
                delimiter = ","
                if "\t" in sample_line:
                    delimiter = "\t"
                    
                reader = csv.DictReader(f, delimiter=delimiter)
                
                for row in reader:
                    total_requests += 1
                    is_success = row.get("success", "true").lower() == "true"
                    resp_code = row.get("responseCode", "200")
                    label = row.get("label", "Unknown Sampler")
                    
                    if not is_success or resp_code.startswith("4") or resp_code.startswith("5"):
                        failed_requests += 1
                        failures.append({
                            "sampler_label": label,
                            "url": row.get("URL", ""),
                            "response_code": resp_code,
                            "response_message": row.get("responseMessage", ""),
                            "failure_message": row.get("failureMessage", ""),
                            "elapsed": row.get("elapsed", "0")
                        })
                        
                if total_requests > 0:
                    success_rate = round(((total_requests - failed_requests) / total_requests) * 100, 2)
        except Exception as e:
            print(f"Failed to parse JTL results: {e}")
    elif result.returncode != 0:
        failed_requests = 1
        failures.append({
            "sampler_label": "JMeter execution",
            "url": "",
            "response_code": str(result.returncode),
            "response_message": "JMeter process failed before producing results",
            "failure_message": result.stderr or result.stdout,
            "elapsed": "0"
        })
        success_rate = 0.0
    elif total_requests == 0:
        failed_requests = 1
        failures.append({
            "sampler_label": "JMeter execution",
            "url": "",
            "response_code": "NO_RESULTS",
            "response_message": "JMeter produced no sample results",
            "failure_message": (
                "JMeter process exited with code 0 but no JTL samples were produced. "
                f"Check {log_path} and confirm the validation JMX contains enabled samplers."
            ),
            "elapsed": "0"
        })
        success_rate = 0.0
            
    # Read log file snippets in case of JMeter runtime exceptions
    log_errors = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                for line in lines[-30:]: # Look at last 30 log lines
                    if "ERROR" in line or "Exception" in line:
                        log_errors.append(line.strip())
        except Exception:
            pass

    return {
        "valid": len(failures) == 0,
        "success_rate": success_rate,
        "xml_success_rate": 100.0,
        "total_requests": total_requests,
        "failed_requests": failed_requests,
        "failures": failures,
        "log_errors": log_errors,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "dry_run_skipped": False,
        "jmeter_executed": True,
        "xml_validation_passed": True,
        "jmeter_command": f"{jmeter_path} -n -t {jmx_path} -l {jtl_path} -j {log_path}",
        "jtl_path": jtl_path,
        "log_path": log_path,
        "skip_reason": ""
    }

def validate_jmx_xml(jmx_path):
    # Step 1: Basic well-formedness check (fast)
    try:
        ET.parse(jmx_path)
    except Exception as exc:
        return {
            "valid": False,
            "success_rate": 0.0,
            "xml_success_rate": 0.0,
            "total_requests": 0,
            "failed_requests": 1,
            "failures": [{
                "sampler_label": "JMX XML validation",
                "url": "",
                "response_code": "XML",
                "response_message": "Invalid JMX XML",
                "failure_message": str(exc),
                "elapsed": "0"
            }],
            "log_errors": [str(exc)],
            "stdout": "",
            "stderr": str(exc),
            "dry_run_skipped": True,
            "jmeter_executed": False,
            "xml_validation_passed": False,
            "jmeter_command": "",
            "jtl_path": "",
            "log_path": "",
            "skip_reason": "JMX XML validation failed before JMeter execution."
        }

    # Step 2: XSD schema validation (thorough)
    xsd_result = validate_jmx_xsd_file(jmx_path)
    if not xsd_result["valid"]:
        error_messages = [f"L{e['line']}: {e['message']}" for e in xsd_result["errors"]]
        error_summary = "; ".join(error_messages[:5])
        print(f"[XSD Validation] Failed with {len(xsd_result['errors'])} error(s): {error_summary}")
        return {
            "valid": False,
            "success_rate": 0.0,
            "xml_success_rate": 0.0,
            "total_requests": 0,
            "failed_requests": 1,
            "failures": [{
                "sampler_label": "JMX XSD schema validation",
                "url": "",
                "response_code": "XSD",
                "response_message": f"XSD validation failed: {len(xsd_result['errors'])} error(s)",
                "failure_message": error_summary,
                "elapsed": "0"
            }],
            "log_errors": error_messages,
            "stdout": "",
            "stderr": error_summary,
            "dry_run_skipped": True,
            "jmeter_executed": False,
            "xml_validation_passed": False,
            "jmeter_command": "",
            "jtl_path": "",
            "log_path": "",
            "skip_reason": f"XSD schema validation failed: {error_summary}"
        }

    print("[XSD Validation] JMX passed XSD schema validation.")
    return {
        "valid": True,
        "success_rate": 100.0,
        "xml_success_rate": 100.0,
        "total_requests": 0,
        "failed_requests": 0,
        "failures": [],
        "log_errors": [],
        "stdout": "",
        "stderr": "",
        "dry_run_skipped": False,
        "jmeter_executed": False,
        "xml_validation_passed": True,
        "jmeter_command": "",
        "jtl_path": "",
        "log_path": "",
        "skip_reason": ""
    }
