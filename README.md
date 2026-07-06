# Vibe Engineering

Vibe Engineering is a multi-agent system that converts a business idea into an
engineering-ready delivery package — and then builds a real, runnable app from it.

A team of specialized AI agents collaborate to produce a product requirements
document, system architecture, API design, UI plan, test plan, and security
review. A **Builder Agent** then turns those artifacts into a working
FastAPI + React project that you can preview live in the browser and download as a ZIP.

```
User Requirement
       |
       v
  Orchestrator
       |
       v
   PM Agent
       |
       v
Architect Agent
       |
       +--------+
       |        |
       v        v
   Backend   Frontend
       |        |
       +--------+
            |
        QA Agent
            |
      Security Agent
            |
      Builder Agent  ──▶  Live Preview + Downloadable Project
            |
       Final Report
```

---

## Installation

### Prerequisites

- **Python 3.11+** (developed on 3.13)
- **Node.js 18+** (developed on 20)
- A **Google Gemini API key** — get one from [Google AI Studio](https://aistudio.google.com/apikey)

### 1. Clone the repository

```bash
git clone <repo-url>
cd Engineering-Delivery-Copilot
```

### 2. Set up the backend

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

Create a `backend/.env` file with your Gemini API key:

```env
GEMINI_API_KEY=your_api_key_here
```

### 3. Set up the frontend

```bash
cd ../frontend
npm install
```

---

## Running Locally

The app needs **two processes running at once** — the backend API and the
frontend — so open two terminals.

### Terminal 1 — Backend API (FastAPI)

```bash
cd backend
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt   # first run only
uvicorn api:app --reload --port 8000
```

- Run `uvicorn` **from inside `backend/`** so the agents can find their prompt
  files (`prompts/*.txt`) and write artifacts to `outputs/`.
- Requires `GEMINI_API_KEY` in `backend/.env` (see [Installation](#installation)).
- Verify it's up: open **http://127.0.0.1:8000/docs**. The frontend expects the
  backend on this exact port.

### Terminal 2 — Frontend (React + Vite)

```bash
cd frontend
npm install                       # first run only
npm run dev
```

Open the printed URL (default **http://localhost:5173**) in your browser. Keep
both terminals running.

### Using the app

1. Enter a business idea / requirement (e.g. *"Build a Hospital Management System"*).
2. The agents generate the full engineering delivery package.
3. Click **Build** to have the Builder Agent generate a runnable project.
4. Click **Preview** to launch the generated app locally and view it live.
5. Click **Download** to get the generated project as a ZIP.

### CLI (optional)

You can also run the agent pipeline without the UI:

```bash
cd backend
python main.py
```

---

## Project Architecture

Vibe Engineering has two runtime layers: a **planning pipeline** (the engineering
agents) and a **build/preview pipeline** (the Builder Agent).

**Planning pipeline** — The orchestrator runs each agent in sequence, feeding one
agent's output into the next. Every agent is a Gemini prompt (`prompts/*.txt`)
plus a thin Python wrapper, and each artifact is cached to `backend/outputs/` so
re-runs are fast and resumable.

| Agent | Input | Output artifact |
|-------|-------|-----------------|
| PM Agent | User requirement | `prd.md` |
| Architect Agent | PRD | `architecture.md` |
| Backend Agent | Architecture | `api_design.md` |
| Frontend Agent | Architecture | `ui_design.md` |
| QA Agent | PRD | `qa_report.md` |
| Security Agent | PRD + Architecture | `security_review.md` |

**Build & preview pipeline** — The Builder Agent reads the generated artifacts and
produces a real project:

```
artifacts ─▶ Builder Agent ─▶ AppSpec ─▶ codegen ─▶ write to disk ─▶ zip ─▶ live preview
```

- **Builder Agent** (`builder/builder_agent.py`) uses the LLM to distil the
  artifacts into a validated `AppSpec` (entities, fields, relationships).
- **codegen** (`builder/codegen.py`) deterministically renders a FastAPI + SQLite
  backend and a React/Vite frontend from the spec.
- **build_service** writes the project to `backend/workspace/generated-project/`
  and packages it as a ZIP.
- **preview_service** launches the generated app on a free local port and only
  reports "running" after a real HTTP 200 from its health endpoint — previews are
  never faked.

**Frontend** — A single-page React + TypeScript app (Vite) that talks to the API
via `axios` and renders artifacts with `react-markdown`.

### Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Python, FastAPI, Uvicorn, Pydantic |
| AI | Google Gemini (`gemini-2.5-flash`) |
| Frontend | React 19, TypeScript, Vite, Axios, react-markdown |
| Generated apps | FastAPI + SQLite (backend), React + Vite (frontend) |

---

## Source Code

```
Engineering-Delivery-Copilot/
├── backend/
│   ├── agents/               # One module per engineering agent
│   │   ├── pm_agent.py
│   │   ├── architect_agent.py
│   │   ├── backend_agent.py
│   │   ├── frontend_agent.py
│   │   ├── qa_agent.py
│   │   └── security_agent.py
│   ├── builder/              # Builder Agent: artifacts → runnable app
│   │   ├── builder_agent.py  # LLM → validated AppSpec
│   │   ├── app_spec.py       # AppSpec data model
│   │   ├── codegen.py        # Deterministic project generation
│   │   ├── build_service.py  # Orchestrates build + packaging
│   │   └── preview_service.py# Runs the generated app locally
│   ├── prompts/              # Prompt templates for each agent
│   ├── outputs/              # Generated artifacts (gitignored)
│   ├── workspace/            # Generated project + ZIP (gitignored)
│   ├── orchestrator.py       # Runs the agent pipeline in order
│   ├── api.py                # FastAPI app (HTTP endpoints)
│   ├── main.py               # CLI entry point for the pipeline
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/Home.tsx    # Main UI
│   │   ├── services/api.ts   # API client
│   │   ├── types/index.ts    # Shared TypeScript types
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
├── PROJECT.md                # Problem, solution, and vision
└── README.md
```

### Key API endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/generate` | Run the agent pipeline for a requirement |
| `POST` | `/build` | Build a runnable project from artifacts |
| `GET`  | `/build/status` | Latest build result |
| `POST` | `/preview/start` | Launch the generated app locally |
| `GET`  | `/preview/status` | Live preview status + logs |
| `POST` | `/preview/stop` | Stop the running preview |
| `GET`  | `/download-project` | Download the generated project as a ZIP |

---

## License

This project is released under the **MIT License** — see [LICENSE](LICENSE) for details.
