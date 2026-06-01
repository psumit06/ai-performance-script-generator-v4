from app.services.parser import parse_postman_collection

with open(r"C:\Users\sumit\OneDrive\Desktop\ai-performance-script-generator\backend\sample_postman.json", "r") as f:

    raw_content = f.read()

result = parse_postman_collection(raw_content)

print(result)