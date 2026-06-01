import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv():
        return False

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

try:
    from google import genai as google_genai
except Exception:
    google_genai = None

legacy_genai = None
if google_genai is None:
    try:
        import google.generativeai as legacy_genai
    except Exception:
        legacy_genai = None

try:
    import anthropic
except Exception:
    anthropic = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


DEFAULT_MODELS = {
    "gemini": "gemini-1.5-flash",
    "claude": "claude-3-5-sonnet-latest",
    "openai": "gpt-4o-mini",
    "grok": "grok-2-latest",
    "groq": "llama-3.3-70b-versatile",
    "github": "openai/gpt-4o-mini",
}

PROVIDER_ALIASES = {
    "anthropic": "claude",
    "xai": "grok",
    "groqcloud": "groq",
    "github_models": "github",
    "github-models": "github",
    "off": "none",
    "disabled": "none",
    "deterministic": "none",
    "no_ai": "none",
    "no-ai": "none",
}


def get_llm_config(provider=None, model=None):
    provider_name = (provider or os.getenv("LLM_PROVIDER") or os.getenv("AI_PROVIDER") or "gemini").strip().lower()
    provider_name = PROVIDER_ALIASES.get(provider_name, provider_name)
    model_name = model or os.getenv("LLM_MODEL") or provider_model_from_env(provider_name) or DEFAULT_MODELS.get(provider_name)

    return {
        "provider": provider_name,
        "model": model_name,
    }


def provider_model_from_env(provider):
    env_names = {
        "gemini": "GEMINI_MODEL",
        "claude": "CLAUDE_MODEL",
        "openai": "OPENAI_MODEL",
        "grok": "GROK_MODEL",
        "groq": "GROQ_MODEL",
        "github": "GITHUB_MODEL",
    }
    return os.getenv(env_names.get(provider, ""))


def is_llm_available(provider=None):
    config = get_llm_config(provider=provider)
    provider_name = config["provider"]

    if provider_name == "none":
        return False
    if provider_name == "gemini":
        return bool((google_genai or legacy_genai) and os.getenv("GEMINI_API_KEY"))
    if provider_name == "claude":
        return bool(anthropic and os.getenv("ANTHROPIC_API_KEY"))
    if provider_name == "openai":
        return bool(OpenAI and os.getenv("OPENAI_API_KEY"))
    if provider_name == "grok":
        return bool(OpenAI and os.getenv("GROK_API_KEY"))
    if provider_name == "groq":
        return bool(OpenAI and os.getenv("GROQ_API_KEY"))
    if provider_name == "github":
        return bool(OpenAI and os.getenv("GITHUB_TOKEN"))
    return False


def generate_text(prompt, provider=None, model=None, temperature=0.1):
    config = get_llm_config(provider=provider, model=model)
    provider_name = config["provider"]
    model_name = config["model"]

    if provider_name == "gemini":
        return generate_with_gemini(prompt, model_name, temperature)
    if provider_name == "claude":
        return generate_with_claude(prompt, model_name, temperature)
    if provider_name == "openai":
        return generate_with_openai(prompt, model_name, os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_BASE_URL"), temperature)
    if provider_name == "grok":
        return generate_with_openai(prompt, model_name, os.getenv("GROK_API_KEY"), os.getenv("GROK_BASE_URL", "https://api.x.ai/v1"), temperature)
    if provider_name == "groq":
        return generate_with_openai(prompt, model_name, os.getenv("GROQ_API_KEY"), os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"), temperature)
    if provider_name == "github":
        return generate_with_openai(prompt, model_name, os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_MODELS_BASE_URL", "https://models.github.ai/inference"), temperature)

    raise RuntimeError(f"Unsupported LLM provider: {provider_name}")


def generate_with_gemini(prompt, model, temperature):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    if google_genai:
        client = google_genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"temperature": temperature},
        )
        return response.text.strip()

    if not legacy_genai:
        raise RuntimeError("google-genai or google-generativeai package is not installed.")

    legacy_genai.configure(api_key=api_key)
    response = legacy_genai.GenerativeModel(model).generate_content(
        prompt,
        generation_config={"temperature": temperature},
    )
    return response.text.strip()


def generate_with_claude(prompt, model, temperature):
    if not anthropic:
        raise RuntimeError("anthropic package is not installed.")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()


def generate_with_openai(prompt, model, api_key, base_url, temperature):
    if not OpenAI:
        raise RuntimeError("openai package is not installed.")
    if not api_key:
        raise RuntimeError("API key is not configured for the selected OpenAI-compatible provider.")

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    client = OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def extract_json_object(text):
    if not text:
        raise ValueError("LLM returned an empty response.")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise
