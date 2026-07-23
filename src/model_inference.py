import json
import requests
from requests.exceptions import RequestException, Timeout
import re

from src.config import DEEPSEEK_API_KEY
deepseek_api = DEEPSEEK_API_KEY

# ============================================================
# 📌 CUSTOMIZE YOUR RESEARCH INTERESTS HERE
# ============================================================
RESEARCH_REQUIREMENTS = """
Your research interests here (e.g. spectral line observations, interstellar medium, star formation)
"""
# You can modify the above text to match your specific research interests.
# Examples:
# - "machine learning, computer vision, natural language processing"
# - "black holes, gravitational waves, neutron stars"
# - "exoplanets, planetary atmospheres, habitability"
# ============================================================

# ============================================================
# 📌 IMPORTANT AUTHORS WATCHLIST
# ============================================================
IMPORTANT_AUTHORS = [
    # "Author Name",

    # Add more authors here (case-insensitive matching)
]
# ============================================================




def fix_invalid_escapes(s: str) -> str:
    # Only allow valid escapes such as \" \\ \/ \b \f \n \r \t
    # Replace any other backslash with \\x
    return re.sub(r'\\(?!["\\/bfnrt])', r'\\\\', s)


def analyze_paper_relevance(paper, use_api=False, api_key=deepseek_api, requirements=None):
    """
    Analyze whether the paper matches the research interests.

    Args:
        paper: Paper dict; must contain an 'Abstract' field.
        use_api: Whether to use the online DeepSeek API.
        api_key: API key.
        requirements: Custom research-interest description (if None, uses global RESEARCH_REQUIREMENTS).

    Returns:
        Dict containing Type, keywords, keywords_CN, Abstract_CN.
    """
    # Check input
    if 'Abstract' not in paper:
        return {"error": "No abstract found in the paper"}

    # Use custom requirements or the default ones
    if requirements is None:
        requirements = RESEARCH_REQUIREMENTS

    # Build the prompt - simplified to a single judgement
    prompt = f"""
    Research interests: {requirements}

    Abstract content: <{paper['Abstract']}>

    Please analyze whether the above abstract is relevant to the research interests.
    - If the content matches the research interests, return Type: "interested"
    - If the content does not match, return Type: "irrelevant"

    Then extract 3-5 English keywords and their corresponding Chinese translations.

    Please output strict JSON with no extra comments or text.
    Return in the following JSON format:
    {{
        "Type": "interested" or "irrelevant",
        "keywords": ["English keyword 1", "English keyword 2", "English keyword 3"...],
        "keywords_CN": ["Chinese keyword 1", "Chinese keyword 2", "Chinese keyword 3"...]
    }}
    """

    prompt_CN = f"""
    Abstract content: <{paper['Abstract']}>

    Please complete the following two tasks:
    1. Translate the abstract into Chinese. Convert formulas directly to HTML-readable format; do not keep LaTeX formatting.
    2. Based on the abstract, extract structured information across the four dimensions below (if a dimension is not mentioned, write "Not mentioned in the abstract"):
       - research_content: research content, including specific data sources (observational data, samples, datasets, etc.) and research objects (celestial bodies, systems, phenomena, etc.)
       - methods: research methods (techniques, models, analysis methods, etc.)
       - discussion: discussion and analysis (interpretation and comparison of the main findings)
       - conclusion: conclusion (final scientific conclusion drawn)

    Please output strict JSON with no extra comments or text.
    Return in the following JSON format:
    {{
        "Abstract_CN": "Chinese translation content",
        "research_content": "Data sources: ...\\nResearch objects: ...",
        "methods": "...",
        "discussion": "...",
        "conclusion": "..."
    }}
    """

    try:
        # Call the LLM for classification according to the selected mode
        if use_api and api_key:
            print('Using online DeepSeek API for classification')
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "system", "content": "You are a research-paper screening assistant. Judge whether a paper is relevant based on the user's research interests."},
                    {"role": "user", "content": prompt},
                ],
                response_format={'type': 'json_object'},
                stream=False
            )
            raw_result = response.choices[0].message.content
        else:
            print('Using local Ollama model for classification')
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": "deepseek-r1:14b", "prompt": prompt, "stream": False},
                timeout=300
            )
            response.raise_for_status()
            raw_result = response.json().get("response", "")

        if not raw_result:
            return {"error": "No valid response from the model"}

        print(f"Classification result:\n{raw_result}")

        # Parse the classification result
        cleaned_output = fix_invalid_escapes(raw_result)
        print(f"Classification result:\n{cleaned_output}")

        try:
            result_dict = parse_model_response(cleaned_output)
            print(f"Classification result 3:\n{result_dict}")
            summary = ""
            print(f"Summary:\n{summary}")
        except Exception as je:
            print(f"Failed to parse JSON response: {je}")
            return {"error": f"Failed to parse response: {je}", "raw_output": cleaned_output}

        # Translate the abstract
        if use_api and api_key:
            print('Using online DeepSeek API for translation')
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            response_CN = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "system", "content": "You are a professional translation assistant."},
                    {"role": "user", "content": prompt_CN},
                ],
                response_format={'type': 'json_object'},
                stream=False
            )
            raw_result_CN = response_CN.choices[0].message.content
        else:
            print('Using local Ollama model for translation')
            response_CN = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": "deepseek-r1:14b", "prompt": prompt_CN, "stream": False},
                timeout=300
            )
            response_CN.raise_for_status()
            raw_result_CN = response_CN.json().get("response", "")

        if not raw_result_CN:
            return {"error": "No valid response from the model"}

        # Parse the translation result
        cleaned_output_CN = fix_invalid_escapes(raw_result_CN)
        print('Translation complete')

        try:
            result_dict_CN = parse_model_response(cleaned_output_CN)
        except Exception as je:
            print(f"Failed to parse JSON response: {je}")
            return {"error": f"Failed to parse response: {je}", "raw_output": cleaned_output_CN}

        # Extract fields
        Type = result_dict.get("Type", "irrelevant")

        # Ensure Type can only be interested or irrelevant
        if Type not in ["interested", "irrelevant"]:
            print(f"Warning: unexpected Type value returned by model: {Type}, setting to 'irrelevant'")
            Type = "irrelevant"

        keywords = result_dict.get("keywords", [])
        keywords_CN = result_dict.get("keywords_CN", [])
        Abstract_CN = result_dict_CN.get("Abstract_CN", "")
        research_content = result_dict_CN.get("research_content", "")
        methods = result_dict_CN.get("methods", "")
        discussion = result_dict_CN.get("discussion", "")
        conclusion = result_dict_CN.get("conclusion", "")

        # Return structured data
        return {
            "Type": Type,
            "keywords": keywords,
            "keywords_CN": keywords_CN,
            "summary": summary,
            "Abstract_CN": Abstract_CN,
            "research_content": research_content,
            "methods": methods,
            "discussion": discussion,
            "conclusion": conclusion,
        }

    except RequestException as e:
        return {"error": f"Request failed: {e}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}


def translate_paper_abstract(paper):
    # Keep the original standalone translation function unchanged
    if 'Abstract' not in paper:
        return {"error": "No abstract found in the paper"}

    prompt = f"""Please translate the following paper abstract into Chinese.
    Abstract content: {paper['Abstract']}
    Please output strict JSON with no extra comments or text.
    Return in the following JSON format:
    {{
        "Abstract_CN": "Chinese translation content"
    }}
    """

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "deepseek-r1:14b",
                "prompt": prompt,
                "stream": False
            },
            timeout=300
        )

        response.raise_for_status()
        raw_result = response.json().get("response", "")
        if not raw_result:
            return {"error": "No valid response from the model"}

        print(f"Raw model output:\n{raw_result}")

        cleaned_output = fix_invalid_escapes(raw_result)

        try:
            result_dict = parse_model_response(cleaned_output)
        except Exception as je:
            print(f"Failed to parse JSON response: {je}")
            return {"error": f"Failed to parse response: {je}", "raw_output": cleaned_output}

        abstract_cn = result_dict.get("Abstract_CN", "").strip()

        return {
            "Abstract_CN": abstract_cn,
        }

    except RequestException as e:
        return {"error": f"Request failed: {e}"}
    except Timeout:
        return {"error": "The request timed out"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}


def parse_model_response(cleaned_output):
    """
    Enhanced JSON parsing helper.
    """
    import re
    import json

    # 1. Try direct parsing
    try:
        return json.loads(cleaned_output)
    except:
        pass

    # 2. Remove possible Markdown code-block markers
    if "" in cleaned_output:
        try:
            parts = cleaned_output.split("")
            if len(parts) > 1:
                json_str = parts[1].split("```")[0].strip()
                return json.loads(json_str)
        except:
            pass

    # 3. Remove ordinary code blocks
    if "```" in cleaned_output:
        try:
            parts = cleaned_output.split("```")
            for part in parts:
                part = part.strip()
                if part and (part.startswith('{') or 'Type' in part or 'Abstract_CN' in part):
                    try:
                        return json.loads(part)
                    except:
                        continue
        except:
            pass

    # 4. Use regex to extract a JSON object
    try:
        # Find the first complete JSON object
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned_output, re.DOTALL)
        if match:
            json_str = match.group(0)
            parsed = json.loads(json_str)
            # Verify it contains expected keys
            if 'Type' in parsed or 'Abstract_CN' in parsed or 'keywords' in parsed:
                return parsed
    except:
        pass

    # 5. Try fixing common JSON errors
    try:
        # Remove comments
        cleaned = re.sub(r'//.*?$', '', cleaned_output, flags=re.MULTILINE)
        cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
        # Try parsing
        return json.loads(cleaned)
    except:
        pass

    # All attempts failed
    print(f"[ERROR] Unable to parse JSON. Raw output:\n{cleaned_output[:1000]}\n")
    return {
        "error": "Failed to parse JSON response",
        "raw_output": cleaned_output[:500]
    }




def check_important_author(paper_authors, important_authors_list=None):
    """
    Robust matching with special character handling.
    """
    if important_authors_list is None:
        important_authors_list = IMPORTANT_AUTHORS

    if not paper_authors or not important_authors_list:
        return False, []

    import re
    import unicodedata

    # Normalize unicode characters
    def normalize(text):
        return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')

    # Normalize and lowercase
    paper_authors = normalize(paper_authors).lower()
    paper_authors = paper_authors.replace(" and ", ", ").replace(";", ",")
    paper_author_list = [author.strip() for author in paper_authors.split(",") if author.strip()]

    matched = []

    for important_author in important_authors_list:
        important_author = normalize(important_author.strip())
        if not important_author:
            continue

        important_lower = important_author.lower()

        # Simple substring match for debugging
        for paper_author in paper_author_list:
            if important_lower in paper_author or paper_author in important_lower:
                matched.append(important_author)
                break

    return len(matched) > 0, matched


def identify_famous_authors(authors, use_api=False, api_key=None):
    """
    Use an LLM to judge whether the author list contains well-known professors.

    Args:
        authors: Author name string (e.g. "Alice Smith, Bob Jones").
        use_api: Whether to use the online DeepSeek API.
        api_key: API key.

    Returns:
        Dict: {
            "has_famous_author": bool,
            "famous_authors": ["Name1", "Name2", ...]
        }
    """
    if not authors or not authors.strip():
        return {"has_famous_author": False, "famous_authors": []}

    if api_key is None:
        api_key = deepseek_api

    prompt = f"""
    The following is the author list of an academic paper:
    {authors}

    Please judge, based on your knowledge, whether these authors include well-known famous professors in academia.
    Only include scholars you are confident have significant influence and are widely recognized in their fields; do not list uncertain authors.

    Please output strict JSON with no extra comments or text.
    Return in the following JSON format:
    {{
        "has_famous_author": true or false,
        "famous_authors": ["Famous professor name 1", "Famous professor name 2", ...]
    }}
    """

    try:
        if use_api and api_key:
            print('Using online DeepSeek API to identify famous professors')
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "system", "content": "You are an academic literature expert familiar with well-known scholars in various fields."},
                    {"role": "user", "content": prompt},
                ],
                response_format={'type': 'json_object'},
                stream=False
            )
            raw_result = response.choices[0].message.content
        else:
            print('Using local Ollama model to identify famous professors')
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": "deepseek-r1:14b", "prompt": prompt, "stream": False},
                timeout=300
            )
            response.raise_for_status()
            raw_result = response.json().get("response", "")

        if not raw_result:
            return {"has_famous_author": False, "famous_authors": []}

        cleaned_output = fix_invalid_escapes(raw_result)
        print(f"Famous professor identification result:\n{cleaned_output}")

        try:
            result_dict = parse_model_response(cleaned_output)
        except Exception as je:
            print(f"Failed to parse famous authors response: {je}")
            return {"has_famous_author": False, "famous_authors": []}

        # Handle the error dict returned when parse_model_response fails
        if isinstance(result_dict, dict) and 'error' in result_dict:
            print(f"Famous professor identification parsing failed: {result_dict.get('error')}")
            return {"has_famous_author": False, "famous_authors": []}

        has_famous = bool(result_dict.get("has_famous_author", False))
        famous_list = result_dict.get("famous_authors", [])
        if not isinstance(famous_list, list):
            famous_list = []

        # Keep only non-empty strings
        famous_list = [name.strip() for name in famous_list if isinstance(name, str) and name.strip()]

        return {
            "has_famous_author": has_famous and len(famous_list) > 0,
            "famous_authors": famous_list
        }

    except RequestException as e:
        print(f"Famous professor identification request failed: {e}")
        return {"has_famous_author": False, "famous_authors": []}
    except Exception as e:
        print(f"Error during famous professor identification: {e}")
        return {"has_famous_author": False, "famous_authors": []}
