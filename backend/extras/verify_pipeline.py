import os
import sys
import json

# Add backend directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.parser_router import parse_api_spec
from app.services.traffic_filter import filter_traffic_with_ai
from app.services.correlation_engine import analyze_correlations
from app.services.logical_reconstructor import reconstruct_logical_flow
from app.services.self_healing import run_self_healing_loop

def main():
    print("====================================================")
    # 1. Read test postman collection
    file_path = "Input_files/sample_postman.json"
    print(f"Loading test file: {file_path}")
    if not os.path.exists(file_path):
        print(f"Error: Could not find {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        raw_content = f.read()

    # 2. Parse API specification
    print("\n--- 1. PARSING INPUT ---")
    parsed_data = parse_api_spec(raw_content)
    endpoints = parsed_data["endpoints"]
    print(f"Parsed {len(endpoints)} endpoints successfully.")

    # 3. Traffic Noise Filtering
    print("\n--- 2. TRAFFIC NOISE FILTERING ---")
    filtered_endpoints, exclusion_regex = filter_traffic_with_ai(endpoints)
    print(f"Noise Filter: Kept {len(filtered_endpoints)} of {len(endpoints)} endpoints.")
    print(f"Generated Exclusion Regex: {exclusion_regex}")

    # 4. Correlation Scan
    print("\n--- 3. CORRELATION LINEAGE SCAN ---")
    correlation_result = analyze_correlations(filtered_endpoints)
    correlated_endpoints = correlation_result["endpoints"]
    correlations = correlation_result["correlations"]
    print(f"Correlation Scan: Identified {len(correlations)} correlations.")
    for c in correlations:
        print(f"   -> Link: Birth [{c['source_index']}] -> Target [{c['target_index']}] using var: \${{{c['var_name']}}}")

    # 5. Timing & Logical Reconstruction
    print("\n--- 4. BROWSER TIMING & RECONSTRUCTION ---")
    logical_flow = reconstruct_logical_flow(correlated_endpoints)
    print(f"Reconstructed {len(logical_flow)} transaction blocks.")
    for tx in logical_flow:
        print(f"   -> Transaction: {tx['transaction_name']} ({len(tx['groups'])} group(s))")

    # 6. Assemble Test Plan
    test_plan = {
        "thread_group": {
            "users": 10,
            "ramp_up": 5,
            "duration": 60,
            "think_time": 1000
        },
        "flow": logical_flow,
        "exclusion_regex": exclusion_regex
    }

    # 7. Execute Dry-Run and Self-Healing Pipeline
    print("\n--- 5. DRY-RUN SIMULATION & SELF-HEALING ---")
    output_path = "output/generated_test_plan_verify.jmx"
    healing_result = run_self_healing_loop(
        test_plan=test_plan,
        original_endpoints=correlated_endpoints,
        output_path=output_path,
        max_retries=2
    )

    print("\n====================================================")
    print("VERIFICATION COMPLETED SUCCESSFULLY!")
    print(f"Validation Status: {'PASSED' if healing_result['success'] else 'FAILED'}")
    print(f"Success Rate: {healing_result['report']['success_rate']}%")
    print(f"Total Samplers Run: {healing_result['report']['total_requests']}")
    print(f"Failed Samplers Count: {healing_result['report']['failed_requests']}")
    print(f"Self-Healing Iterations Run: {healing_result['iterations']}")
    print(f"JMX Script Saved To: {output_path}")
    print("====================================================")

if __name__ == "__main__":
    main()
