from app.services.postman_parser import parse_postman
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_parse_postman(file_path):
    """Test Postman collection parsing."""
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return None
    
    with open(file_path, "r", encoding="utf-8") as f:
        raw_content = f.read()
    
    result = parse_postman(raw_content)
    print(f"Parsed {len(result.get('endpoints', []))} endpoints")
    return result

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_parse_postman(sys.argv[1])
    else:
        print("Usage: python testparser.py <path_to_postman_collection.json>")