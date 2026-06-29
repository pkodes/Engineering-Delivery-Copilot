import axios from "axios";
import type {
  BuildResult,
  GenerateRequest,
  GenerateResponse,
  PreviewState,
} from "../types";

export const API_BASE = "http://127.0.0.1:8000";

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    "Content-Type": "application/json",
  },
});

export const generateArtifacts = async (
  payload: GenerateRequest
): Promise<GenerateResponse> => {
  const response = await api.post<GenerateResponse>("/generate", payload);
  return response.data;
};

export const buildProject = async (payload: {
  requirement: string;
  artifacts?: GenerateResponse;
}): Promise<BuildResult> => {
  const response = await api.post<BuildResult>("/build", payload);
  return response.data;
};

export const startPreview = async (): Promise<PreviewState> => {
  const response = await api.post<PreviewState>("/preview/start");
  return response.data;
};

export const getPreviewStatus = async (): Promise<PreviewState> => {
  const response = await api.get<PreviewState>("/preview/status");
  return response.data;
};

export const stopPreview = async (): Promise<PreviewState> => {
  const response = await api.post<PreviewState>("/preview/stop");
  return response.data;
};

export const downloadProjectUrl = `${API_BASE}/download-project`;

export default api;
