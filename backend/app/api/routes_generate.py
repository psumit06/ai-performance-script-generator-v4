import json
import os
import queue
import threading
from typing import List, Optional
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Query,
    HTTPException
)
from fastapi.responses import StreamingResponse
from app.services.parser_router import (
    parse_api_spec
)
from app.services.traffic_filter import (
    filter_traffic_with_ai
)
from app.services.correlation_engine import (
    analyze_correlations
)
from app.services.logical_reconstructor import (
    reconstruct_logical_flow
)
from app.services.self_healing import (
    run_self_healing_loop
)
from app.services.llm_provider import (
    DEFAULT_MODELS,
    get_llm_config,
    is_llm_available
)
from app.services.csv_parser import (
    parse_csv_file,
    validate_csv_for_jmeter
)
from app.services.csv_parameterizer import (
    parameterize_endpoints_from_csv
)
from app.services.functional_parameterizer import (
    analyze_functional_parameterization,
    apply_functional_parameterization,
    load_rules_json
)

router = APIRouter()


async def process_csv_uploads(csv_files: Optional[List[UploadFile]] = None):
    csv_data_list = []
    if not csv_files:
        return csv_data_list

    MAX_CSV_FILE_SIZE = 15 * 1024 * 1024  # 15MB
    for csv_file in csv_files:
        if not csv_file.filename:
            continue

        csv_content = await csv_file.read()
        if len(csv_content) > MAX_CSV_FILE_SIZE:
            print(f"CSV file {csv_file.filename} too large. Maximum size is {MAX_CSV_FILE_SIZE // (1024*1024)}MB. Skipping.")
            continue

        csv_content = csv_content.decode("utf-8", errors="ignore")
        parsed_csv = parse_csv_file(csv_content, csv_file.filename)

        if parsed_csv.get("error"):
            print(f"CSV parsing error for {csv_file.filename}: {parsed_csv['error']}")
            continue

        validation = validate_csv_for_jmeter(parsed_csv)
        if not validation["valid"]:
            print(f"CSV validation failed for {csv_file.filename}: {validation['errors']}")
            continue

        csv_data_list.append(parsed_csv)
        print(f"CSV file processed: {csv_file.filename} with {len(parsed_csv['variables'])} variables, {parsed_csv['row_count']} rows")

    return csv_data_list


async def read_rules_upload(replacement_rules: Optional[UploadFile] = None):
    if not replacement_rules or not replacement_rules.filename:
        return {"rules": []}
    raw_rules = await replacement_rules.read()
    try:
        return load_rules_json(raw_rules.decode("utf-8", errors="ignore"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REPLACEMENT_RULES",
                "message": f"Replacement rules JSON is invalid: {exc}"
            }
        )


def parse_selected_candidate_ids(selected_parameterization_ids: str | None):
    if not selected_parameterization_ids:
        return set()
    try:
        parsed = json.loads(selected_parameterization_ids)
        if isinstance(parsed, list):
            return {str(item) for item in parsed}
    except json.JSONDecodeError:
        pass
    return {item.strip() for item in selected_parameterization_ids.split(",") if item.strip()}

@router.get("/llm-providers")
def llm_providers():
    active = get_llm_config()
    return {
        "active_provider": active["provider"],
        "active_model": active["model"],
        "providers": [
            {
                "name": name,
                "default_model": model,
                "configured": is_llm_available(name)
            }
            for name, model in DEFAULT_MODELS.items()
        ]
    }


@router.post("/analyze-parameterization")
async def analyze_parameterization(
    file: UploadFile = File(...),
    csv_files: Optional[List[UploadFile]] = File(default=None),
    replacement_rules: Optional[UploadFile] = File(default=None)
):
    raw_content = await file.read()
    raw_content = raw_content.decode("utf-8", errors="ignore")
    csv_data_list = await process_csv_uploads(csv_files)
    rules_config = await read_rules_upload(replacement_rules)

    parsed_data = parse_api_spec(raw_content)
    all_endpoints = parsed_data["endpoints"]
    candidates = analyze_functional_parameterization(all_endpoints, rules_config)
    parameterize_endpoints_from_csv(all_endpoints, csv_data_list)

    pre_selected_ids = [c["id"] for c in candidates if c.get("selected_by_default")]

    return {
        "filename": file.filename,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "pre_selected_ids": pre_selected_ids,
        "csv_files": [
            {
                "filename": csv["filename"],
                "variables": csv["variables"],
                "row_count": csv["row_count"]
            }
            for csv in csv_data_list
        ],
        "rules_loaded": len(rules_config.get("rules", []))
    }

@router.post("/generate-from-file")
async def generate_from_file(
    users: int,
    ramp_up: int,
    duration: int,
    think_time: int,
    pacing: int = Query(default=0),
    ai_enabled: bool = Query(default=True),
    llm_provider: str | None = Query(default=None),
    llm_model: str | None = Query(default=None),
    functional_parameterization: bool = Query(default=False),
    selected_parameterization_ids: str | None = Query(default=None),
    file: UploadFile = File(...),
    csv_files: Optional[List[UploadFile]] = File(default=None),
    replacement_rules: Optional[UploadFile] = File(default=None)
):
    try:
        effective_provider = llm_provider if ai_enabled else "none"
        effective_model = llm_model if ai_enabled else None

        if ai_enabled and llm_provider and not is_llm_available(llm_provider):
            config = get_llm_config(provider=llm_provider, model=llm_model)
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "LLM_PROVIDER_NOT_CONFIGURED",
                    "message": (
                        f"The selected LLM provider '{config['provider']}' is not configured properly. "
                        "Please select a different provider or configure its API key in backend/.env."
                    ),
                    "provider": config["provider"],
                    "model": config["model"]
                }
            )

        # =====================================
        # 1. READ FILE CONTENT
        # =====================================
        raw_content = await file.read()
        
        # Validate file size (max 100MB for main file, 15MB for CSV files)
        MAX_MAIN_FILE_SIZE = 100 * 1024 * 1024  # 100MB
        if len(raw_content) > MAX_MAIN_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Main file too large. Maximum size is {MAX_MAIN_FILE_SIZE // (1024*1024)}MB. Received: {len(raw_content) // (1024*1024)}MB"
            )
        
        raw_content = raw_content.decode("utf-8", errors="ignore")
        print(f"File received: {file.filename}")

        # =====================================
        # 1.5. PROCESS CSV FILES (if any)
        # =====================================
        csv_data_list = await process_csv_uploads(csv_files)

        # =====================================
        # 2. SCHEMA INGESTION & PARSING
        # =====================================
        parsed_data = parse_api_spec(raw_content)
        all_endpoints = parsed_data["endpoints"]
        parameterize_endpoints_from_csv(all_endpoints, csv_data_list)
        parameterization_candidates = []
        applied_parameterizations = []
        if functional_parameterization:
            rules_config = await read_rules_upload(replacement_rules)
            selected_ids = None
            if selected_parameterization_ids is not None:
                selected_ids = parse_selected_candidate_ids(selected_parameterization_ids)
            parameterization_candidates = analyze_functional_parameterization(all_endpoints, rules_config)
            applied_parameterizations = apply_functional_parameterization(
                all_endpoints,
                parameterization_candidates,
                selected_ids=selected_ids,
                include_auto_apply=True
            )
            print(f"Functional Parameterization: Applied {len(applied_parameterizations)} of {len(parameterization_candidates)} candidates.")
        print(f"Ingested {len(all_endpoints)} endpoints.")

        # =====================================
        # 3. AI TRAFFIC FILTERING (Noise Exclusions)
        # =====================================
        filtered_endpoints, exclusion_regex = filter_traffic_with_ai(
            all_endpoints,
            llm_provider=effective_provider,
            llm_model=effective_model
        )
        print(f"Traffic Filter: Kept {len(filtered_endpoints)} of {len(all_endpoints)} endpoints.")

        # =====================================
        # 4. AI CORRELATION ENGINE (Lineage scan)
        # =====================================
        correlation_result = analyze_correlations(
            filtered_endpoints,
            llm_provider=effective_provider,
            llm_model=effective_model
        )
        correlated_endpoints = correlation_result["endpoints"]
        detected_correlations = correlation_result["correlations"]
        print(f"Correlation Engine: Identified {len(detected_correlations)} dynamic parameter correlations.")

        # =====================================
        # 5. BROWSER TIMING & RECONSTRUCTION
        # =====================================
        logical_flow = reconstruct_logical_flow(
            correlated_endpoints,
            llm_provider=effective_provider,
            llm_model=effective_model,
            base_think_time=think_time
        )
        print(f"Logical Reconstruction: Grouped into {len(logical_flow)} transaction blocks.")

        # =====================================
        # 6. ASSEMBLE TEST PLAN
        # =====================================
        test_plan = {
            "thread_group": {
                "users": users,
                "ramp_up": ramp_up,
                "duration": duration,
                "think_time": think_time,
                "pacing": pacing
            },
            "flow": logical_flow,
            "exclusion_regex": exclusion_regex,
            "csv_files": csv_data_list
        }

        # =====================================
        # 7. SELF-HEALING VALIDATION LOOP (SSE Streaming)
        # =====================================
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        output_dir = os.path.join(backend_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "generated_test_plan.jmx")

        # Use a queue to stream logs from the blocking self-healing loop to SSE
        log_queue = queue.Queue()

        def on_log(log_type, message):
            log_queue.put({"type": "log", "log_type": log_type, "message": message})

        def run_healing():
            try:
                result = run_self_healing_loop(
                    test_plan=test_plan,
                    original_endpoints=correlated_endpoints,
                    output_path=output_path,
                    max_retries=3,
                    llm_provider=effective_provider,
                    llm_model=effective_model,
                    on_log=on_log
                )
                log_queue.put({"type": "result", "data": result})
            except Exception as e:
                log_queue.put({"type": "error", "message": str(e)})
            finally:
                log_queue.put(None)  # Sentinel to signal completion

        # Run self-healing in a background thread
        healing_thread = threading.Thread(target=run_healing, daemon=True)
        healing_thread.start()

        def event_stream():
            try:
                while True:
                    item = log_queue.get()
                    if item is None:
                        break
                    if item["type"] == "log":
                        yield f"event: log\ndata: {json.dumps({'log_type': item['log_type'], 'message': item['message']})}\n\n"
                    elif item["type"] == "result":
                        healing_result = item["data"]
                        # Build the final response payload
                        response_data = {
                            "success": healing_result["success"],
                            "filename": file.filename,
                            "success_rate": healing_result["report"]["success_rate"],
                            "total_requests": healing_result["report"]["total_requests"],
                            "failed_requests": healing_result["report"]["failed_requests"],
                            "failures": healing_result["report"]["failures"],
                            "validation": {
                                "valid": healing_result["report"].get("valid", False),
                                "xml_validation_passed": healing_result["report"].get("xml_validation_passed", False),
                                "xml_success_rate": healing_result["report"].get("xml_success_rate", 0.0),
                                "jmeter_executed": healing_result["report"].get("jmeter_executed", False),
                                "dry_run_skipped": healing_result["report"].get("dry_run_skipped", False),
                                "skip_reason": healing_result["report"].get("skip_reason", ""),
                                "jmeter_command": healing_result["report"].get("jmeter_command", ""),
                                "jtl_path": healing_result["report"].get("jtl_path", ""),
                                "log_path": healing_result["report"].get("log_path", ""),
                                "log_errors": healing_result["report"].get("log_errors", [])
                            },
                            "jmx_content": healing_result["jmx_content"],
                            "correlations": detected_correlations,
                            "healing_history": healing_result["healing_history"],
                            "exclusion_regex": exclusion_regex,
                            "ai_enabled": ai_enabled,
                            "llm_provider": effective_provider,
                            "llm_model": effective_model,
                            "execution_profile": {
                                "users": users,
                                "ramp_up": ramp_up,
                                "duration": duration,
                                "think_time": think_time,
                                "pacing": pacing
                            },
                            "csv_files": [
                                {
                                    "filename": csv["filename"],
                                    "variables": csv["variables"],
                                    "row_count": csv["row_count"]
                                }
                                for csv in csv_data_list
                            ],
                            "functional_parameterization": {
                                "enabled": functional_parameterization,
                                "candidate_count": len(parameterization_candidates),
                                "applied_count": len(applied_parameterizations),
                                "candidates": parameterization_candidates,
                                "applied": applied_parameterizations
                            },
                            "flow": logical_flow,
                            "endpoints": [
                                {
                                    "name": ep.get("name"),
                                    "method": ep.get("method"),
                                    "url": ep.get("full_url"),
                                    "kept": ep.get("ai_decision", {}).get("keep", True),
                                    "reason": ep.get("ai_decision", {}).get("reason", ""),
                                    "extractors": ep.get("extractors", [])
                                }
                                for ep in all_endpoints
                            ]
                        }
                        yield f"event: result\ndata: {json.dumps(response_data)}\n\n"
                    elif item["type"] == "error":
                        yield f"event: error\ndata: {json.dumps({'error': item['message']})}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Pipeline Generation Error: {str(e)}")
        traceback.print_exc()
        return {
            "error": "An internal error occurred while processing the request. Please check the server logs for details.",
            "error_type": type(e).__name__
        }
