from agents.frontend_agent import FRONTEND_PROMPT
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

with open("prompts/security_prompt.txt") as f:
    SECURITY_PROMPT = f.read()

def run_security_agent(prd: str, architecture: str):

    model = genai.GenerativeModel(
        "gemini-2.5-flash"
    )

    response = model.generate_content(
        f"""
        {SECURITY_PROMPT}

        Product Requirements Document:

        {prd}

        Architecture Document:

        {architecture}
        """
    )

    return response.text