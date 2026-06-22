import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

with open("prompts/architect_prompt.txt") as f:
    ARCHITECT_PROMPT = f.read()


def run_architect_agent(prd: str):

    model = genai.GenerativeModel(
        "gemini-2.5-flash"
    )

    response = model.generate_content(
        f"""
        {ARCHITECT_PROMPT}

        Product Requirements Document:

        {prd}
        """
    )

    return response.text