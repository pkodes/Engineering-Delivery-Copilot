export interface GenerateRequest {
  requirement: string;
}

export interface GenerateResponse {
  prd: string;
  architecture: string;
  backend: string;
  frontend: string;
  qa: string;
  security: string;
}

export interface BuildLog {
  stage: string;
  level: "info" | "warn" | "error";
  message: string;
}

export interface BuildResult {
  status: "success" | "error";
  project_name: string;
  slug: string;
  app_title: string;
  description: string;
  entities: string[];
  files: string[];
  file_count: number;
  zip_available: boolean;
  spec: unknown;
  logs: BuildLog[];
  error: string | null;
}

export interface PreviewState {
  status: "idle" | "starting" | "running" | "error" | "stopped";
  url: string | null;
  port: number | null;
  app_title: string;
  pid: number | null;
  error: string | null;
  logs: BuildLog[];
  output: string[];
}
