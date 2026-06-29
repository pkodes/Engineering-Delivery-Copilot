import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

with open("prompts/qa_prompt.txt", "r") as f:
    QA_PROMPT = f.read()


def run_qa_agent(prd: str):

    model = genai.GenerativeModel(
        "gemini-2.5-flash"
    )

    response = model.generate_content(
        f"""
        {QA_PROMPT}

        Product Requirements Document:

        {prd}
        """
    )

    return response.text