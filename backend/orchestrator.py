import os

from agents.pm_agent import run_pm_agent
from agents.architect_agent import run_architect_agent
from agents.backend_agent import run_backend_agent
from agents.frontend_agent import run_frontend_agent
from agents.qa_agent import run_qa_agent
from agents.security_agent import run_security_agent


OUTPUT_DIR = "outputs"


def save_artifact(filename: str, content: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(
        os.path.join(OUTPUT_DIR, filename),
        "w",
        encoding="utf-8"
    ) as f:
        f.write(content)


def generate_artifacts(requirement: str):

    artifacts = {}

    # 1. PM Agent / PRD
    prd_path = os.path.join(OUTPUT_DIR, "prd.md")
    if os.path.exists(prd_path):
        print("Loading PRD from cache...")
        with open(prd_path, "r", encoding="utf-8") as f:
            prd = f.read()
    else:
        print("Running PM Agent...")
        prd = run_pm_agent(requirement)
        save_artifact("prd.md", prd)
    artifacts["prd"] = prd

    # 2. Architect Agent / Architecture
    arch_path = os.path.join(OUTPUT_DIR, "architecture.md")
    if os.path.exists(arch_path):
        print("Loading Architecture from cache...")
        with open(arch_path, "r", encoding="utf-8") as f:
            architecture = f.read()
    else:
        print("Running Architect Agent...")
        architecture = run_architect_agent(prd)
        save_artifact("architecture.md", architecture)
    artifacts["architecture"] = architecture

    # 3. Backend Agent / API Design
    backend_path = os.path.join(OUTPUT_DIR, "api_design.md")
    if os.path.exists(backend_path):
        print("Loading Backend Design from cache...")
        with open(backend_path, "r", encoding="utf-8") as f:
            backend_design = f.read()
    else:
        print("Running Backend Agent...")
        backend_design = run_backend_agent(architecture)
        save_artifact("api_design.md", backend_design)
    artifacts["backend"] = backend_design

    # 4. Frontend Agent / UI Design
    frontend_path = os.path.join(OUTPUT_DIR, "ui_design.md")
    if os.path.exists(frontend_path):
        print("Loading Frontend Design from cache...")
        with open(frontend_path, "r", encoding="utf-8") as f:
            frontend_design = f.read()
    else:
        print("Running Frontend Agent...")
        frontend_design = run_frontend_agent(architecture)
        save_artifact("ui_design.md", frontend_design)
    artifacts["frontend"] = frontend_design

    # 5. QA Agent / QA Report
    qa_path = os.path.join(OUTPUT_DIR, "qa_report.md")
    if os.path.exists(qa_path):
        print("Loading QA Report from cache...")
        with open(qa_path, "r", encoding="utf-8") as f:
            qa_report = f.read()
    else:
        print("Running QA Agent...")
        qa_report = run_qa_agent(prd)
        save_artifact("qa_report.md", qa_report)
    artifacts["qa"] = qa_report

    # 6. Security Agent / Security Review
    security_path = os.path.join(OUTPUT_DIR, "security_review.md")
    if os.path.exists(security_path):
        print("Loading Security Review from cache...")
        with open(security_path, "r", encoding="utf-8") as f:
            security_review = f.read()
    else:
        print("Running Security Agent...")
        security_review = run_security_agent(prd, architecture)
        save_artifact("security_review.md", security_review)
    artifacts["security"] = security_review

    return artifacts