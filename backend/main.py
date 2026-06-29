from orchestrator import generate_artifacts

requirement = """
Build a Hospital Management System
"""

artifacts = generate_artifacts(
    requirement
)

print(
    "\nAll artifacts generated successfully."
)