"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { artifactUrl, fetchJob, type JobResponse } from "../lib/api";

type Props = {
  jobId: string;
  initialJob: JobResponse;
};

export function JobDetail({ jobId, initialJob }: Props) {
  const [job, setJob] = useState<JobResponse>(initialJob);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!["queued", "running"].includes(job.status)) {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await fetchJob(jobId);
        setJob(nextJob);
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Failed to refresh job.");
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [job.status, jobId]);

  const statusClassName = useMemo(
    () => `status-pill ${job.status === "succeeded" ? "succeeded" : job.status === "failed" ? "failed" : job.status === "running" ? "running" : ""}`,
    [job.status],
  );

  return (
    <div className="marketing-shell workbench-shell">
      <section className="inner-hero workbench-hero">
        <span className="eyebrow">Job Detail</span>
        <h1>{job.job_type.replaceAll("_", " ")}</h1>
        <div className="job-detail-topline">
          <Link className="button-ghost" href="/workbench">
            Back to Workbench
          </Link>
        </div>
        <div className={statusClassName}>
          <strong>{job.status}</strong>
          <span>confidence {job.confidence.toFixed(2)}</span>
        </div>
        <p>Job ID: {job.job_id}</p>
        {job.error_message ? <p>{job.error_message}</p> : null}
        {error ? <p>{error}</p> : null}
      </section>

      <section className="job-summary-grid">
        <article className="job-summary-card">
          <small>Status</small>
          <strong>{job.status}</strong>
        </article>
        <article className="job-summary-card">
          <small>Artifacts</small>
          <strong>{job.artifacts.length}</strong>
        </article>
        <article className="job-summary-card">
          <small>Review items</small>
          <strong>{job.review_items.length}</strong>
        </article>
        <article className="job-summary-card">
          <small>Issues</small>
          <strong>{job.issues.length}</strong>
        </article>
      </section>

      <div className="card-grid two workbench-detail-grid">
        <section className="marketing-card">
          <h2>Job Status</h2>
          <div className="step-list">
            {job.step_results.map((step) => (
              <article key={step.step_name} className="step-card">
                <strong>{step.step_name}</strong>
                <div className="step-meta">
                  <span>{step.status}</span>
                  <span>confidence {step.confidence.toFixed(2)}</span>
                  {step.started_at ? <span>started {step.started_at}</span> : null}
                  {step.finished_at ? <span>finished {step.finished_at}</span> : null}
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="marketing-card">
          <h2>Artifacts</h2>
          {job.artifacts.length ? (
            <div className="artifact-list">
              {job.artifacts.map((artifact) => (
                <article key={artifact.artifact_id} className="artifact-card">
                  <strong>{artifact.kind}</strong>
                  <div className="artifact-meta">
                    <span>{artifact.mime_type}</span>
                    <span>{artifact.size_bytes} bytes</span>
                    <span>{artifact.step_name}</span>
                  </div>
                  <div className="action-row">
                    <a className="button-secondary" href={artifactUrl(artifact.artifact_id)} target="_blank" rel="noreferrer">
                      Download
                    </a>
                    <Link className="button-secondary" href={`/workbench/jobs/${job.job_id}/artifacts/${artifact.artifact_id}`}>
                      Preview
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="empty-state">Artifacts will appear when the job produces files.</p>
          )}
        </section>
      </div>

      <div className="card-grid two top-gap">
        <section className="marketing-card">
          <h2>Review Items</h2>
          {job.review_items.length ? (
            <div className="review-list">
              {job.review_items.map((item, index) => (
                <article key={`${item.field_key}-${index}`} className="review-card">
                  <strong>{item.field_key}</strong>
                  <div className="review-meta">
                    <span>{item.reason_code}</span>
                    <span>confidence {item.confidence.toFixed(2)}</span>
                    <span>{item.source_kind}</span>
                  </div>
                  <p>{item.predicted_value || "(empty)"}</p>
                  {item.raw_text ? <p className="empty-state">raw: {item.raw_text}</p> : null}
                </article>
              ))}
            </div>
          ) : (
            <p className="empty-state">No review items for this job.</p>
          )}
        </section>

        <section className="marketing-card">
          <h2>Issues</h2>
          {job.issues.length ? (
            <div className="review-list">
              {job.issues.map((issue, index) => (
                <article key={`${issue.code}-${index}`} className="review-card">
                  <strong>{issue.code}</strong>
                  <p>{issue.message}</p>
                  <div className="review-meta">
                    <span>{issue.severity}</span>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="empty-state">No issues recorded.</p>
          )}
        </section>
      </div>
    </div>
  );
}
