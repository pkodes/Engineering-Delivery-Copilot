from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from builder.build_service import (
    build_project,
    get_last_result,
    get_zip_path,
    read_cached_artifacts,
)
from builder.preview_service import preview_service
from orchestrator import generate_artifacts


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Ensure the generated preview process never outlives the platform server.
    preview_service.stop()


app = FastAPI(title="VibeForge API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequirementRequest(BaseModel):
    requirement: str


class BuildRequest(BaseModel):
    requirement: str
    # Optional artifacts from the engineering team. If omitted, the most recent
    # artifacts on disk (outputs/) are used.
    artifacts: Optional[dict] = None


@app.get("/")
def home():
    return {"message": "VibeForge API"}


@app.post("/generate")
def generate(req: RequirementRequest):
    return generate_artifacts(req.requirement)


@app.post("/build")
def build(req: BuildRequest):
    """Run the Builder Agent: generate a real, runnable project from the artifacts."""
    artifacts = req.artifacts or read_cached_artifacts()
    result = build_project(req.requirement, artifacts)
    return result.to_dict()


@app.get("/build/status")
def build_status():
    """Return the most recent build result (or a neutral 'idle' status)."""
    result = get_last_result()
    if result is None:
        return {"status": "idle"}
    return result.to_dict()


@app.post("/preview/start")
def preview_start():
    """Run the generated application locally and expose a live Preview URL."""
    return preview_service.start().to_dict()


@app.get("/preview/status")
def preview_status():
    """Current preview state: status, URL, deploy logs, and process output."""
    return preview_service.status().to_dict()


@app.post("/preview/stop")
def preview_stop():
    """Stop the running preview process."""
    preview_service.stop()
    return preview_service.status().to_dict()


@app.get("/download-project")
def download_project():
    """Download the generated project as a ZIP archive."""
    zip_path = get_zip_path()
    if zip_path is None:
        raise HTTPException(
            status_code=404,
            detail="No generated project found. Run a build first via POST /build.",
        )
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename="generated-project.zip",
    )
