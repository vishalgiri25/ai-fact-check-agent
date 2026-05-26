from openai import OpenAI
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Initialize OpenRouter client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

def extract_claims(text):

    prompt = f"""
Extract ALL factual claims from the text.

IMPORTANT:
- Extract EVERY claim, even if it sounds false, mythical, outdated, or scientifically incorrect.
- Do NOT skip claims.
- One claim per line.
- Return ONLY bullet points.
- No headings.
- No explanations.

TEXT:
{text}
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
            temperature=0
        )
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "Unauthorized" in error_msg:
            raise Exception("API key error: Please check your OPENROUTER_API_KEY")
        elif "429" in error_msg or "rate limit" in error_msg.lower():
            raise Exception("API rate limit exceeded: Please try again in a moment")
        elif "timeout" in error_msg.lower():
            raise Exception("API request timeout: Service is slow, please try again")
        else:
            raise Exception(f"API error: {error_msg}")

    response = completion.choices[0].message.content.strip()
    
    # Clean up: remove any intro text before the first bullet point
    lines = response.split("\n")
    claims_lines = []
    for line in lines:
        line = line.strip()
        if line.startswith("•") or line.startswith("-"):
            claims_lines.append(line)
    
    return "\n".join(claims_lines)