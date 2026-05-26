import requests
import os
from dotenv import load_dotenv

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Trusted sources for fact-checking
TRUSTED_DOMAINS = {
    "nasa.gov": 10,
    "wikipedia.org": 9,
    "britannica.com": 9,
    "bbc.com": 9,
    "sciencedaily.com": 8,
    "space.com": 8,
    "nationalgeographic.com": 8,
    "archive.org": 8,
    "mit.edu": 8,
    "harvard.edu": 8,
    "stanford.edu": 8,
    "nature.com": 8,
    "science.org": 8,
    "snopes.com": 9,  # Fact-checking site
    "factcheck.org": 9,  # Fact-checking site
    "bbc.co.uk": 9,
    "reuters.com": 8,
    "ap.org": 8,
}

def get_source_reliability(url):
    """Score URL reliability based on domain"""
    url_lower = url.lower()
    for domain, score in TRUSTED_DOMAINS.items():
        if domain in url_lower:
            return score
    return 0  # Unknown source

def search_web(query):

    url = "https://api.tavily.com/search"

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",  # Better results
        "max_results": 10,  # Get more to filter
        "include_answer": True
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()  # Raise exception for bad status codes
    except requests.exceptions.Timeout:
        raise Exception("Search service timeout: Request took too long, please try again")
    except requests.exceptions.ConnectionError:
        raise Exception("Search service unavailable: Network connection error")
    except requests.exceptions.HTTPError as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise Exception("Search API key error: TAVILY_API_KEY may be invalid")
        elif "429" in error_msg:
            raise Exception("Search rate limit: Too many requests, please try again later")
        else:
            raise Exception(f"Search service error: {error_msg}")
    except Exception as e:
        raise Exception(f"Search service error: {str(e)}")

    try:
        data = response.json()
    except:
        raise Exception("Search service returned invalid response")

    results = []

    for result in data.get("results", []):
        result_obj = {
            "title": result.get("title"),
            "content": result.get("content"),
            "url": result.get("url"),
            "reliability": get_source_reliability(result.get("url", ""))
        }
        results.append(result_obj)

    # Sort by reliability (trusted sources first)
    results.sort(key=lambda x: x["reliability"], reverse=True)
    
    # Return top 5 results, prioritizing reliable sources
    return results[:5]