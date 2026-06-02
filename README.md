Step 1: Verify AI Provider Connectivity
cd backend
python -c "
from app.services.llm_provider import is_llm_available, generate_text
print('AI Available:', is_llm_available())
response = generate_text('Say hello in one word.')
print('AI Response:', response)
"
Step 2: Test Parsing (no AI needed)
cd backend
python -c "
from app.services.parser_router import parse_api_spec
with open('Input_files/sample_postman.json', 'r') as f:
    data = parse_api_spec(f.read())
print(f'Parsed {len(data[\"endpoints\"])} endpoints')
"
Step 3: Test Full Pipeline with Self-Healing
cd backend
python extras/verify_pipeline.py
This runs the complete pipeline: parse → traffic filter → correlation → reconstruction → dry-run → self-healing. Check for:

Validation Status: PASSED
Success Rate: 100%
No ERROR or Exception in output
Step 4: Test via API (end-to-end)
cd backend
uvicorn app.main:app --reload
Then upload a Postman/HAR file through the frontend UI at http://localhost:8000.

Step 5: Verify JMeter Dry-Run Works
cd backend
python -c "
from app.services.execution_validator import run_jmeter
import os
jmx = 'output/generated_test_plan.jmx'
if os.path.exists(jmx):
    result = run_jmeter(jmx)
    print('Valid:', result['valid'])
    print('Success Rate:', result['success_rate'])
else:
    print('Run Step 3 first to generate a JMX')
"
This confirms JMeter is installed and reachable at the configured path.
