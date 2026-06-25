def clean_ai_xml(response):

    # Remove markdown code blocks
    response = response.replace("```xml", "")
    response = response.replace("```", "")

    # Trim spaces/newlines
    response = response.strip()

    return response