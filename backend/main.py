from agents.pm_agent import run_pm_agent
from agents.architect_agent import run_architect_agent
from agents.backend_agent import run_backend_agent
from agents.frontend_agent import run_frontend_agent
import time


requirement = """
Build a Hospital Management System
"""

prd = run_pm_agent(requirement)

with open("outputs/prd.md", "w") as f:
    f.write(prd)

architecture = run_architect_agent(prd)

print("Project Requirements generated")
time.sleep(15)



with open("outputs/architecture.md", "w") as f:
    f.write(architecture)

print("Architecture generated")
time.sleep(15)


backend_design = run_backend_agent(architecture)

with open("outputs/api_design.md", "w") as f:
    f.write(backend_design)

print("API Design generated")
time.sleep(15)

frontend_design = run_frontend_agent(architecture)

with open("outputs/ui_design.md", "w") as f:
    f.write(frontend_design)

print("Frontend design generated")
time.sleep(15)
