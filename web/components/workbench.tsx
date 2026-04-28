"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE_URL } from "../lib/api";

type SubmitState = {
  loading: boolean;
  error: string;
};

function defaultState(): SubmitState {
  return { loading: false, error: "" };
}

async function submitJob(
  endpoint: string,
  formData: FormData,
): Promise<{ job_id: string }> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await parseApiError(response, endpoint));
  }
  return response.json();
}

async function parseApiError(response: Response, endpoint: string): Promise<string> {
  try {
    const payload = await response.json();
    const detail = payload?.detail;
    if (typeof detail === "string" && detail) {
      return detail;
    }
    if (detail && typeof detail === "object") {
      const code = typeof detail.code === "string" ? detail.code : "";
      const message = typeof detail.message === "string" ? detail.message : "";
      if (code && message) {
        return `${message} (${code})`;
      }
      if (message) {
        return message;
      }
    }
  } catch {
    // Fall back to text below.
  }
  const text = await response.text().catch(() => "");
  return text || `Request failed for ${endpoint}`;
}

export function Workbench() {
  const router = useRouter();
  const [pipelineState, setPipelineState] = useState<SubmitState>(defaultState);
  const [provider, setProvider] = useState("ollama");
  const [stepState, setStepState] = useState<Record<string, SubmitState>>({
    analyze: defaultState(),
    prepare: defaultState(),
    extract: defaultState(),
    assemble: defaultState(),
  });

  const forms = useMemo(
    () => [
      {
        key: "analyze",
        title: "Analyze Template",
        action: "/jobs/analyze-template",
        fileLabels: [{ name: "template_file", label: "Template PDF" }],
      },
      {
        key: "prepare",
        title: "Prepare Fillable",
        action: "/jobs/prepare-fillable",
        fileLabels: [{ name: "template_file", label: "Template PDF" }],
      },
      {
        key: "extract",
        title: "Extract Data",
        action: "/jobs/extract-data",
        fileLabels: [
          { name: "filled_file", label: "Filled Form" },
          { name: "fillable_file", label: "Fillable PDF" },
        ],
      },
      {
        key: "assemble",
        title: "Assemble Final PDF",
        action: "/jobs/assemble",
        fileLabels: [
          { name: "fillable_file", label: "Fillable PDF" },
          { name: "extraction_json", label: "Extraction JSON" },
        ],
      },
    ],
    [],
  );

  const workbenchHighlights = useMemo(
    () => [
      { label: "Best for", value: "Template + completed form" },
      { label: "Outputs", value: "Fillable PDF, data, and final packet" },
      { label: "Review", value: "Visible confidence and review cues" },
    ],
    [],
  );

  async function handleFullPipeline(formData: FormData) {
    setPipelineState({ loading: true, error: "" });
    try {
      const job = await submitJob("/jobs/run-pipeline", formData);
      router.push(`/workbench/jobs/${job.job_id}`);
    } catch (error) {
      setPipelineState({
        loading: false,
        error: error instanceof Error ? error.message : "Pipeline request failed.",
      });
      return;
    }
    setPipelineState(defaultState());
  }

  async function handleStepSubmit(key: string, action: string, formData: FormData) {
    setStepState((current) => ({
      ...current,
      [key]: { loading: true, error: "" },
    }));
    try {
      const job = await submitJob(action, formData);
      router.push(`/workbench/jobs/${job.job_id}`);
    } catch (error) {
      setStepState((current) => ({
        ...current,
        [key]: {
          loading: false,
          error: error instanceof Error ? error.message : "Job request failed.",
        },
      }));
      return;
    }
    setStepState((current) => ({ ...current, [key]: defaultState() }));
  }

  return (
    <div className="marketing-shell workbench-shell">
      <section className="inner-hero workbench-hero">
        <span className="eyebrow">Operational Workbench</span>
        <h1>Run the live pipeline, inspect artifacts, and compare OCR modes.</h1>
        <p className="hero-text">
          This surface stays operational. Upload documents, choose managed OpenAI OCR or private local GLM / Ollama,
          then inspect job status, review items, and final artifacts.
        </p>
        <div className="workbench-highlight-strip">
          {workbenchHighlights.map((item) => (
            <article key={item.label} className="workbench-highlight-card">
              <span className="workbench-highlight-label">{item.label}</span>
              <strong>{item.value}</strong>
            </article>
          ))}
        </div>
      </section>

      <div className="card-grid two workbench-main-grid">
        <section className="marketing-card jumbo">
          <h2>Run Full Pipeline</h2>
          <p>Upload both inputs and let FormAI analyze, generate, extract, and assemble in one async job.</p>
          <div className="workbench-intake-note">
            <div>
              <small>Recommended input</small>
              <strong>One blank template and one completed form</strong>
            </div>
            <div>
              <small>Typical result</small>
              <strong>Fillable PDF, structured data, and final assembled form</strong>
            </div>
          </div>
          <div className="provider-switcher">
            <span className="provider-label">OCR mode</span>
            <div className="provider-options">
              <button
                type="button"
                className={provider === "openai" ? "provider-card selected" : "provider-card"}
                onClick={() => setProvider("openai")}
              >
                <strong>OpenAI</strong>
                <span>Managed cloud workflow for convenience and speed</span>
              </button>
              <button
                type="button"
                className={provider === "ollama" ? "provider-card selected" : "provider-card"}
                onClick={() => setProvider("ollama")}
              >
                <strong>Local GLM / Ollama</strong>
                <span>Private local path for sensitive-data positioning</span>
              </button>
            </div>
            <p className="provider-helper">
              Use OpenAI for convenience, or choose Local GLM / Ollama when you want a more private workflow story.
            </p>
          </div>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const formData = new FormData(event.currentTarget);
              formData.set("vision_provider", provider);
              await handleFullPipeline(formData);
            }}
          >
            <div className="field-row">
              <label htmlFor="template_file">Template PDF</label>
              <input id="template_file" name="template_file" type="file" accept="application/pdf" required />
            </div>
            <div className="field-row">
              <label htmlFor="filled_file">Filled Form</label>
              <input id="filled_file" name="filled_file" type="file" accept="application/pdf,image/*" required />
            </div>
            <div className="action-row">
              <button className="button-primary" type="submit" disabled={pipelineState.loading}>
                {pipelineState.loading ? "Starting..." : "Run Full Pipeline"}
              </button>
            </div>
            {pipelineState.error ? <p className="error-text">{pipelineState.error}</p> : null}
          </form>
        </section>

        <section className="marketing-card">
          <h2>Step-by-Step Tools</h2>
          <p>Use the individual job endpoints when you want to inspect each stage separately.</p>
          <div className="workbench-step-grid">
            {forms.map((item) => (
              <form
                key={item.key}
                onSubmit={async (event) => {
                  event.preventDefault();
                  const formData = new FormData(event.currentTarget);
                  formData.set("vision_provider", provider);
                  await handleStepSubmit(item.key, item.action, formData);
                }}
                className="step-form-card"
              >
                <span className="step-form-kicker">{item.key.replaceAll("_", " ")}</span>
                <h3>{item.title}</h3>
                {item.fileLabels.map((field) => (
                  <div key={field.name} className="field-row">
                    <label htmlFor={field.name}>{field.label}</label>
                    <input
                      id={field.name}
                      name={field.name}
                      type="file"
                      accept={field.name.includes("json") ? "application/json" : field.name.includes("template") || field.name.includes("fillable") ? "application/pdf" : "application/pdf,image/*"}
                      required
                    />
                  </div>
                ))}
                <div className="action-row">
                  <button
                    className="button-secondary"
                    type="submit"
                    disabled={stepState[item.key]?.loading}
                  >
                    {stepState[item.key]?.loading ? "Starting..." : item.title}
                  </button>
                </div>
                {stepState[item.key]?.error ? <p className="error-text">{stepState[item.key]?.error}</p> : null}
              </form>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
