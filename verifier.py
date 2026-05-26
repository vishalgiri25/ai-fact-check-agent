from web_search import search_web
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

def verify_claim(claim):

    try:
        web_results = search_web(claim)
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "API key" in error_msg:
            raise Exception("Search API key error: Please check your TAVILY_API_KEY")
        elif "rate limit" in error_msg.lower():
            raise Exception("Search API rate limit: Too many requests, please try again later")
        else:
            raise Exception(f"Search service unavailable: {error_msg}")

    # Filter to only reliable sources (reliability score > 0)
    reliable_results = [r for r in web_results if r.get("reliability", 0) > 0]
    
    # Track if we have reliable evidence
    has_reliable_sources = len(reliable_results) > 0
    
    # If no reliable sources, use what we have, but mark them as unreliable
    if not reliable_results:
        reliable_results = web_results[:3]
    
    evidence_text = ""

    for i, result in enumerate(reliable_results[:5]):  # Use top 5 reliable sources
        reliability_marker = "RELIABLE SOURCE" if result.get("reliability", 0) > 0 else "UNVERIFIED SOURCE"
        evidence_text += f"""
        Source #{i+1} - {reliability_marker}
        Title: {result['title']}
        Content: {result['content']}
        URL: {result['url']}
        ---
        """

    # Build prompt
    if not has_reliable_sources:
        evidence_quality = "WARNING: No reliable sources found for this claim. Be EXTRA STRICT."
    else:
        evidence_quality = "Good: Reliable sources available for fact-checking."
    
    prompt = f"""
SYSTEM: You are an EXTREMELY STRICT fact-checker. Your ONLY job is to REJECT false claims. Be ruthless.

{evidence_quality}

CRITICAL INSTRUCTION:
- ASSUME claims are FALSE until proven TRUE by reliable sources
- If evidence doesn't 100% support the claim → mark FALSE
- If there's ANY contradiction → mark FALSE
- If evidence is missing → mark FALSE
- VERIFIED is ONLY for claims explicitly supported by reliable sources

MUST-REJECT EXAMPLES (these are ALL FALSE):
- "Earth has 3 moons" → FALSE (Earth has 1, not 3)
- "Humans use 10% of their brain" → FALSE (We use 100%)
- "Goldfish have 3 second memory" → FALSE (They remember longer)
- "The Great Wall is visible from space" → FALSE (Not without aid)
- "Sugar makes kids hyperactive" → FALSE (No scientific proof)

CLAIM TO VERIFY:
{claim}

RELIABLE SOURCES (from NASA, Wikipedia, Britannica, BBC, etc):
{evidence_text}

STRICT VERIFICATION STEPS:
1. What does the claim state EXACTLY?
2. What do RELIABLE SOURCES say about this?
3. Is there ANY contradiction between the claim and reliable sources?
4. Is the evidence 100% clear and direct?
5. If you have ANY DOUBT → mark FALSE

Your decision (be STRICT):

Return EXACTLY:

Status: VERIFIED or INACCURATE or FALSE

Explanation:
(one sentence reason)

Correct Fact:
(if wrong, state correct fact from reliable sources)
"""

    try:
        completion = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2
        )
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "Unauthorized" in error_msg:
            raise Exception("Verification API key error: Please check your OPENROUTER_API_KEY")
        elif "429" in error_msg or "rate limit" in error_msg.lower():
            raise Exception("Verification API rate limit: Too many requests, try again later")
        elif "timeout" in error_msg.lower():
            raise Exception("Verification service timeout: Service is slow, try again")
        else:
            raise Exception(f"Verification API error: {error_msg}")

    verification_result = completion.choices[0].message.content

    lines = verification_result.split("\n")

    status = ""
    explanation = ""
    correct_fact = ""

    for line in lines:

        if line.startswith("Status:"):
            status = line.replace("Status:", "").strip()

        elif line.startswith("Explanation:"):
            explanation = line.replace("Explanation:", "").strip()

        elif line.startswith("Correct Fact:"):
            correct_fact = line.replace("Correct Fact:", "").strip()

    return {
        "claim": claim,
        "status": status,
        "explanation": explanation,
        "correct_fact": correct_fact,
        "evidence": web_results
    }