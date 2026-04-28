export const API_BASE_URL =
  process.env.NEXT_PUBLIC_FORMAI_API_BASE_URL ?? "http://127.0.0.1:8000";

export type ArtifactDescriptor = {
  artifact_id: string;
  kind: string;
  path: string;
  mime_type: string;
  size_bytes: number;
  step_name: string;
  created_at: string;
  download_url: string;
};

export type StepResult = {
  step_name: string;
  status: string;
  started_at: string;
  finished_at: string;
  confidence: number;
  artifact_ids: string[];
  issues: Array<{ code: string; message: string; severity: string; context?: Record<string, string> }>;
  data: Record<string, unknown>;
};

export type JobResponse = {
  job_id: string;
  job_type: string;
  status: string;
  created_at: string;
  updated_at: string;
  step_results: StepResult[];
  artifacts: ArtifactDescriptor[];
  issues: Array<{ code: string; message: string; severity: string; context?: Record<string, string> }>;
  review_items: Array<{
    field_key: string;
    predicted_value: string;
    confidence: number;
    reason_code: string;
    raw_text: string;
    source_kind: string;
  }>;
  confidence: number;
  error_message: string;
};

export async function fetchJob(jobId: string): Promise<JobResponse> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load job ${jobId}`);
  }
  return response.json();
}

export function artifactUrl(artifactId: string): string {
  return `${API_BASE_URL}/artifacts/${artifactId}`;
}
