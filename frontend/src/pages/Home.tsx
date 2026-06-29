import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  buildProject,
  downloadProjectUrl,
  generateArtifacts,
  startPreview,
} from "../services/api";
import type { BuildLog, BuildResult, GenerateResponse, PreviewState } from "../types";

interface Agent {
  id: string;
  name: string;
  role: string;
  avatar: string;
  color: string;
  thinking: string;
}

const AGENTS: Agent[] = [
  { id: "pm", name: "Sarah PM", role: "Product Manager Agent", avatar: "PM", color: "#8b5cf6", thinking: "Defining product requirements & user stories…" },
  { id: "architect", name: "Alex Architect", role: "Software Architect Agent", avatar: "AR", color: "#3b82f6", thinking: "Designing system architecture & data flow…" },
  { id: "backend", name: "Linus Backend", role: "Backend Engineer Agent", avatar: "BE", color: "#10b981", thinking: "Specifying API endpoints & data schemas…" },
  { id: "frontend", name: "Ada Frontend", role: "Frontend Architect Agent", avatar: "FE", color: "#06b6d4", thinking: "Crafting UI components & user flows…" },
  { id: "qa", name: "Grace QA", role: "QA Engineer Agent", avatar: "QA", color: "#f59e0b", thinking: "Writing test plans & edge cases…" },
  { id: "security", name: "Bruce Security", role: "Security Engineer Agent", avatar: "SE", color: "#ef4444", thinking: "Auditing for vulnerabilities & risks…" },
];

// The 7th team member: turns the artifacts into a real, running application.
const BUILDER: Agent = {
  id: "builder",
  name: "Forge Builder",
  role: "Build & Deploy Agent",
  avatar: "BD",
  color: "#22c55e",
  thinking: "Generating code, installing dependencies & launching a live preview…",
};

const ALL_AGENTS: Agent[] = [...AGENTS, BUILDER];
const BUILDER_INDEX = ALL_AGENTS.length - 1;

const BUILD_HINTS = [
  "Reading the engineering artifacts…",
  "Designing the data model with Gemini…",
  "Generating the FastAPI backend…",
  "Generating the React + Vite frontend…",
  "Packaging the project…",
  "Launching the live preview…",
];

const ARTIFACT_SECTIONS: { key: keyof GenerateResponse; title: string; agentId: string }[] = [
  { key: "prd", title: "Product Requirements (PRD)", agentId: "pm" },
  { key: "architecture", title: "System Architecture", agentId: "architect" },
  { key: "backend", title: "API Design", agentId: "backend" },
  { key: "frontend", title: "UI/UX Design", agentId: "frontend" },
  { key: "qa", title: "QA Test Plan", agentId: "qa" },
  { key: "security", title: "Security Review", agentId: "security" },
];
const AGENT_BY_ID = Object.fromEntries(ALL_AGENTS.map((a) => [a.id, a]));

type AgentStatus = "idle" | "thinking" | "completed";
type Phase = "idle" | "collaborating" | "building" | "done";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export const Home: React.FC = () => {
  const [requirement, setRequirement] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<GenerateResponse | null>(null);

  const [phase, setPhase] = useState<Phase>("idle");
  const [activeAgentIndex, setActiveAgentIndex] = useState<number>(-1);
  const [agentStatuses, setAgentStatuses] = useState<AgentStatus[]>(
    Array(ALL_AGENTS.length).fill("idle")
  );
  const [selectedTab, setSelectedTab] = useState<string>("all");

  // Builder + preview state
  const [build, setBuild] = useState<BuildResult | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [logLines, setLogLines] = useState<BuildLog[]>([]);
  const [hintIdx, setHintIdx] = useState(0);

  const buildConsoleRef = useRef<HTMLDivElement>(null);
  const loading = phase === "collaborating" || phase === "building";
  const completedCount = agentStatuses.filter((s) => s === "completed").length;

  const setStatus = (i: number, s: AgentStatus) =>
    setAgentStatuses((prev) => {
      const next = [...prev];
      next[i] = s;
      return next;
    });

  // Cycle honest build-stage hints while we wait on the (single) build call.
  useEffect(() => {
    if (phase !== "building") return;
    const id = setInterval(() => setHintIdx((i) => (i + 1) % BUILD_HINTS.length), 2200);
    return () => clearInterval(id);
  }, [phase]);

  // Keep the build console pinned to the newest line.
  useEffect(() => {
    if (buildConsoleRef.current) {
      buildConsoleRef.current.scrollTop = buildConsoleRef.current.scrollHeight;
    }
  }, [logLines]);

  const revealLogs = async (logs: BuildLog[]) => {
    for (const line of logs) {
      setLogLines((prev) => [...prev, line]);
      await sleep(140);
    }
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!requirement.trim() || loading) return;

    setError(null);
    setArtifacts(null);
    setBuild(null);
    setPreview(null);
    setLogLines([]);
    setSelectedTab("all");
    setAgentStatuses(Array(ALL_AGENTS.length).fill("idle"));
    setActiveAgentIndex(0);
    setPhase("collaborating");

    // 1. Kick off artifact generation in parallel with the animation.
    let apiResult: GenerateResponse | null = null;
    let apiError: unknown = null;
    const apiCall = generateArtifacts({ requirement })
      .then((d) => { apiResult = d; })
      .catch((err) => { apiError = err; });

    for (let i = 0; i < AGENTS.length; i++) {
      setActiveAgentIndex(i);
      setStatus(i, "thinking");
      await sleep(1100);
      if (i === AGENTS.length - 1) await apiCall;
      if (apiError) {
        setError(apiError instanceof Error ? apiError.message : "Failed to generate artifacts.");
        setPhase("idle");
        setAgentStatuses(Array(ALL_AGENTS.length).fill("idle"));
        setActiveAgentIndex(-1);
        return;
      }
      setStatus(i, "completed");
      await sleep(200);
    }
    if (!apiResult) {
      setError("No artifacts were returned by the server.");
      setPhase("idle");
      return;
    }
    setArtifacts(apiResult);

    // 2. Builder Agent: generate the real project, then launch a live preview.
    setPhase("building");
    setActiveAgentIndex(BUILDER_INDEX);
    setStatus(BUILDER_INDEX, "thinking");

    let buildResult: BuildResult;
    try {
      buildResult = await buildProject({ requirement, artifacts: apiResult });
    } catch (err) {
      buildResult = {
        status: "error",
        project_name: "", slug: "", app_title: "", description: "",
        entities: [], files: [], file_count: 0, zip_available: false, spec: null,
        logs: [{ stage: "build", level: "error", message: "Build request failed — is the backend running?" }],
        error: err instanceof Error ? err.message : String(err),
      };
    }
    setBuild(buildResult);
    await revealLogs(buildResult.logs);

    if (buildResult.status === "success") {
      let previewState: PreviewState;
      try {
        previewState = await startPreview();
      } catch (err) {
        previewState = {
          status: "error", url: null, port: null, app_title: buildResult.app_title, pid: null,
          error: err instanceof Error ? err.message : String(err),
          logs: [{ stage: "preview", level: "error", message: "Preview request failed." }],
          output: [],
        };
      }
      setPreview(previewState);
      if (previewState.logs?.length) await revealLogs(previewState.logs);
    }

    setStatus(BUILDER_INDEX, "completed");
    setActiveAgentIndex(ALL_AGENTS.length);
    setPhase("done");
  };

  const getTabLabel = (key: string): string => {
    switch (key) {
      case "prd": return "Product Requirements";
      case "architecture": return "System Architecture";
      case "backend": return "API Design";
      case "frontend": return "UI/UX Design";
      case "qa": return "QA Test Plan";
      case "security": return "Security Review";
      default: return "All Artifacts";
    }
  };

  const renderArtifactSection = (
    section: { key: keyof GenerateResponse; title: string; agentId: string },
    markdown: string
  ) => {
    const agent = AGENT_BY_ID[section.agentId];
    return (
      <section key={section.key} className="card artifact-section reveal">
        <div className="artifact-section-head">
          <span className="artifact-section-chip" style={{ backgroundColor: agent?.color, boxShadow: `0 0 10px ${agent?.color}55` }}>
            {agent?.avatar}
          </span>
          <div>
            <h2 className="artifact-section-title">{section.title}</h2>
            <span className="artifact-section-author">by {agent?.name}</span>
          </div>
        </div>
        <div className="markdown-body">
          <ReactMarkdown>{markdown}</ReactMarkdown>
        </div>
      </section>
    );
  };

  const activeAgent = activeAgentIndex >= 0 && activeAgentIndex < ALL_AGENTS.length ? ALL_AGENTS[activeAgentIndex] : null;

  return (
    <div className="main-grid">
      {/* Left: requirements + team roster */}
      <div className="left-panel">
        <div className="card input-card">
          <h2 style={{ marginBottom: "0.75rem", fontSize: "1.1rem", fontWeight: 700 }}>New Project</h2>
          <form onSubmit={handleGenerate}>
            <div className="form-group">
              <label htmlFor="requirement-input">Software Idea & Requirements</label>
              <textarea
                id="requirement-input"
                className="textarea-input"
                value={requirement}
                onChange={(e) => setRequirement(e.target.value)}
                placeholder="Describe your software idea (e.g., Build a Hospital Management System)..."
                disabled={loading}
              />
            </div>
            <button type="submit" className="generate-button" disabled={loading || !requirement.trim()}>
              {loading ? (<><span className="thinking-dot" style={{ background: "white" }} />{phase === "building" ? "Building…" : "Collaborating…"}</>) : "Generate & Build App"}
            </button>
          </form>
        </div>

        <div className="card team-card">
          <h3 className="panel-title"><span />AI Engineering Team</h3>
          <div className="agent-list">
            {ALL_AGENTS.map((agent, index) => {
              const status = agentStatuses[index];
              const isBuilder = agent.id === "builder";
              return (
                <div key={agent.id} className={`agent-card status-${status}${isBuilder ? " builder-card" : ""}`}>
                  <div className="agent-info">
                    <div className="agent-avatar" style={{
                      backgroundColor: status === "thinking" ? agent.color : undefined,
                      borderColor: status !== "idle" ? agent.color : undefined,
                      color: status !== "idle" ? "#ffffff" : undefined,
                    }}>
                      {status === "completed" ? "✓" : agent.avatar}
                    </div>
                    <div className="agent-details">
                      <span className="agent-name">{agent.name}</span>
                      <span className="agent-role">{agent.role}</span>
                    </div>
                  </div>
                  <div className="agent-status-badge">
                    {status === "thinking" && <span className="thinking-dot" />}
                    {status === "thinking" ? "Working..." : status === "completed" ? "Completed" : "Waiting"}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Right: live workspace → result */}
      <div className="right-panel">
        {error && (
          <div className="card error-card" style={{ marginBottom: "1rem" }}>
            <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <h4 style={{ fontWeight: 700, marginBottom: "0.25rem" }}>Generation Failed</h4>
              <p style={{ fontSize: "0.9rem" }}>{error}</p>
            </div>
          </div>
        )}

        {phase === "idle" && (
          <div className="card empty-state">
            <svg width="64" height="64" fill="none" stroke="currentColor" strokeWidth="1" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <h3>Ready to Collaborate</h3>
            <p>Describe your idea on the left. The AI team will design it, then build & deploy a working app.</p>
          </div>
        )}

        {(phase === "collaborating" || phase === "building") && (
          <div className="card workspace-card">
            <div className="workspace-header">
              <span className={`live-badge${phase === "building" ? " done" : ""}`}>
                <span className="live-pulse" />{phase === "building" ? "BUILDING" : "LIVE"}
              </span>
              <h3>{phase === "building" ? "Forge Builder is assembling your application" : "Engineering Team Collaborating"}</h3>
              <p>{phase === "building" ? "Generating real code, then deploying a live preview — never faked." : "Six specialized agents are drafting your delivery package in real time."}</p>
            </div>

            {phase === "collaborating" && (
              <div className="workspace-progress">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${(completedCount / AGENTS.length) * 100}%` }} />
                </div>
                <span className="progress-label">{Math.min(completedCount, AGENTS.length)} / {AGENTS.length} agents complete</span>
              </div>
            )}

            {activeAgent && (
              <div className="spotlight">
                <div className="spotlight-avatar" style={{ backgroundColor: activeAgent.color }}>
                  {activeAgent.avatar}
                  <span className="spotlight-ring" style={{ borderColor: activeAgent.color }} />
                </div>
                <div className="spotlight-info">
                  <span className="spotlight-name">{activeAgent.name}</span>
                  <span className="spotlight-role">{activeAgent.role}</span>
                  <span className="spotlight-thinking">
                    <span className="thinking-dot" />
                    {phase === "building" ? (build ? "Launching live preview…" : BUILD_HINTS[hintIdx]) : activeAgent.thinking}
                  </span>
                </div>
              </div>
            )}

            {phase === "collaborating" ? (
              <div className="activity-feed">
                <span className="activity-feed-title">Activity</span>
                {AGENTS.map((agent, i) => {
                  const status = agentStatuses[i];
                  if (status === "idle") return null;
                  return (
                    <div key={agent.id} className={`activity-row status-${status}`}>
                      <span className="activity-icon" style={{ borderColor: agent.color, color: status === "completed" ? "#34d399" : agent.color }}>
                        {status === "completed" ? "✓" : <span className="thinking-dot" />}
                      </span>
                      <span className="activity-text"><strong>{agent.name}</strong> {status === "completed" ? "delivered their work" : agent.thinking}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="logs-console" ref={buildConsoleRef}>
                <span className="activity-feed-title">Build & deployment logs</span>
                {logLines.length === 0 ? (
                  <div className="log-line info muted">Working… logs will stream here.</div>
                ) : (
                  logLines.map((l, i) => <div key={i} className={`log-line ${l.level}`}>{l.message}</div>)
                )}
              </div>
            )}
          </div>
        )}

        {phase === "done" && (
          <div className="result-scroll">
            {build && <ResultHero build={build} preview={preview} logLines={logLines} />}
            {artifacts && (
              <div className="artifacts-container" style={{ marginTop: "1.25rem" }}>
                <div className="artifacts-subtitle">Engineering Artifacts</div>
                <div className="tabs-nav">
                  <button className={`tab-button ${selectedTab === "all" ? "active" : ""}`} onClick={() => setSelectedTab("all")}>All Artifacts</button>
                  {ARTIFACT_SECTIONS.map(({ key }) => (
                    <button key={key} className={`tab-button ${selectedTab === key ? "active" : ""}`} onClick={() => setSelectedTab(key)}>
                      {getTabLabel(key)}
                    </button>
                  ))}
                </div>
                {selectedTab === "all" ? (
                  <div className="artifact-static-feed">
                    {ARTIFACT_SECTIONS.map((section) => renderArtifactSection(section, artifacts[section.key]))}
                  </div>
                ) : (
                  <div className="card artifact-content">
                    <div className="markdown-body">
                      <ReactMarkdown>{artifacts[selectedTab as keyof GenerateResponse] || ""}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const ResultHero: React.FC<{ build: BuildResult; preview: PreviewState | null; logLines: BuildLog[] }> = ({ build, preview, logLines }) => {
  const success = build.status === "success";
  const previewReady = preview?.status === "running" && !!preview.url;

  return (
    <div className={`hero-card ${success ? "ok" : "fail"}`}>
      {success ? (
        <>
          <div className="hero-badge">✅ Project Generated</div>
          <h2 className="hero-title">{build.app_title}</h2>
          <p className="hero-sub">
            {build.file_count} files · {build.entities.length} modules
            {build.entities.length > 0 ? ` · ${build.entities.join(", ")}` : ""}
          </p>

          <div className="hero-block">
            <div className="hero-block-label">🌐 Live Preview</div>
            {previewReady ? (
              <div className="hero-row">
                <a className="hero-btn primary" href={preview!.url!} target="_blank" rel="noreferrer">Open Application →</a>
                <span className="hero-url">{preview!.url}</span>
              </div>
            ) : (
              <div className="hero-preview-fail">
                Live preview unavailable{preview?.error ? `: ${preview.error}` : ""}. The generated source is still ready to download.
              </div>
            )}
          </div>

          <div className="hero-block">
            <div className="hero-block-label">📦 Download Source Code</div>
            <a className="hero-btn" href={downloadProjectUrl}>Download generated-project.zip</a>
          </div>
        </>
      ) : (
        <>
          <div className="hero-badge fail">⚠️ Build Failed</div>
          <p className="hero-sub">{build.error || "The build did not complete."}</p>
          {build.zip_available && (
            <div className="hero-block">
              <div className="hero-block-label">📦 Download Source Code</div>
              <a className="hero-btn" href={downloadProjectUrl}>Download last generated-project.zip</a>
            </div>
          )}
        </>
      )}

      <details className="logs-details">
        <summary>Build & deployment logs ({logLines.length})</summary>
        <div className="logs-console embedded">
          {logLines.map((l, i) => <div key={i} className={`log-line ${l.level}`}>{l.message}</div>)}
        </div>
      </details>
    </div>
  );
};

export default Home;
