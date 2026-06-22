import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

with open("prompts/pm_prompt.txt", "r") as f:
    PM_PROMPT = f.read()


def run_pm_agent(requirement: str):

    model = genai.GenerativeModel(
        "gemini-2.5-flash"
    )

    response = model.generate_content(
        f"""
        {PM_PROMPT}

        Requirement:

        {requirement}
        """
    )

    return response.text