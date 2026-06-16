"""
CSV Parser Service
Parses uploaded CSV files and extracts headers/variables for JMeter CSV Data Set Config.
"""
import csv
import io
from typing import List, Dict, Any, Optional


def parse_csv_file(content: str, filename: str) -> Dict[str, Any]:
    """
    Parse a CSV file and extract headers (variable names) and row count.
    
    Args:
        content: Raw CSV file content as string
        filename: Name of the uploaded CSV file
        
    Returns:
        Dictionary containing:
            - filename: Original filename
            - variables: List of column headers (variable names)
            - row_count: Number of data rows (excluding header)
            - sample_row: First data row for preview (optional)
            - delimiter: Detected delimiter
            - error: Error message if parsing failed
    """
    result = {
        "filename": filename,
        "variables": [],
        "row_count": 0,
        "sample_row": None,
        "delimiter": ",",
        "error": None
    }
    
    if not content or not content.strip():
        result["error"] = "Empty CSV file"
        return result
    
    try:
        # Detect delimiter
        delimiter = detect_delimiter(content)
        result["delimiter"] = delimiter
        
        # Parse CSV
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        
        # Read header row
        header_row = next(reader, None)
        if not header_row:
            result["error"] = "No header row found in CSV"
            return result
        
        # Clean header names (strip whitespace, replace spaces with underscores)
        variables = []
        for header in header_row:
            clean_name = header.strip()
            if clean_name:
                # Replace spaces with underscores for JMeter compatibility
                clean_name = clean_name.replace(" ", "_")
                variables.append(clean_name)
        
        result["variables"] = variables
        
        # Count data rows and get sample
        row_count = 0
        sample_row = None
        
        for row in reader:
            if row:  # Skip empty rows
                row_count += 1
                if sample_row is None and len(row) >= len(variables):
                    sample_row = row[:len(variables)]  # Take only as many columns as headers
        
        result["row_count"] = row_count
        result["sample_row"] = sample_row
        
        return result
        
    except csv.Error as e:
        result["error"] = f"CSV parsing error: {str(e)}"
        return result
    except Exception as e:
        result["error"] = f"Failed to parse CSV: {str(e)}"
        return result


def detect_delimiter(content: str) -> str:
    """
    Detect the delimiter used in the CSV file.
    
    Args:
        content: Raw CSV content
        
    Returns:
        Detected delimiter character (default: comma)
    """
    # Try common delimiters
    delimiters = [',', ';', '\t', '|']
    
    # Get first few lines for analysis
    lines = content.strip().split('\n')[:5]
    
    if not lines:
        return ','
    
    # Count occurrences of each delimiter in the first line
    scores = {}
    for delimiter in delimiters:
        count = lines[0].count(delimiter)
        if count > 0:
            scores[delimiter] = count
    
    if not scores:
        return ','
    
    # Return delimiter with highest count
    return max(scores, key=scores.get)


def sanitize_variable_name(name: str) -> str:
    """
    Sanitize a variable name for JMeter compatibility.
    
    Args:
        name: Raw variable name
        
    Returns:
        Sanitized variable name
    """
    if not name:
        return "unnamed_var"
    
    # Replace spaces with underscores
    sanitized = name.strip().replace(" ", "_")
    
    # Remove or replace invalid characters (keep alphanumeric and underscore)
    sanitized = ''.join(c if c.isalnum() or c == '_' else '_' for c in sanitized)
    
    # Ensure it starts with a letter or underscore
    if sanitized and sanitized[0].isdigit():
        sanitized = '_' + sanitized
    
    return sanitized or "unnamed_var"


def validate_csv_for_jmeter(parsed_csv: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate parsed CSV data for JMeter compatibility.
    
    Args:
        parsed_csv: Output from parse_csv_file
        
    Returns:
        Validation result with status and any warnings
    """
    result = {
        "valid": True,
        "warnings": [],
        "errors": []
    }
    
    if parsed_csv.get("error"):
        result["valid"] = False
        result["errors"].append(parsed_csv["error"])
        return result
    
    variables = parsed_csv.get("variables", [])
    row_count = parsed_csv.get("row_count", 0)
    
    # Check for variables
    if not variables:
        result["valid"] = False
        result["errors"].append("No variable names found in CSV header")
        return result
    
    # Check for data rows
    if row_count == 0:
        result["warnings"].append("CSV file has no data rows")
    
    # Check variable name count
    if len(variables) > 100:
        result["warnings"].append(f"Large number of variables ({len(variables)}). Consider reducing for better performance.")
    
    # Check for duplicate variable names
    seen = set()
    duplicates = []
    for var in variables:
        if var in seen:
            duplicates.append(var)
        seen.add(var)
    
    if duplicates:
        result["warnings"].append(f"Duplicate variable names found: {', '.join(duplicates[:5])}")
    
    return result
