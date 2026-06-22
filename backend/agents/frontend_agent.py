import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

with open("prompts/frontend_prompt.txt") as f:
    FRONTEND_PROMPT = f.read()

def run_frontend_agent(architecture: str):

    model = genai.GenerativeModel(
        "gemini-2.5-flash"
    )

    response = model.generate_content(
        f"""
        {FRONTEND_PROMPT}

        Architecture Document:

        {architecture}
        """
    )

    return response.text