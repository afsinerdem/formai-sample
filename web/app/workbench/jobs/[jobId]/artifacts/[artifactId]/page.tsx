import Link from "next/link";
import { notFound } from "next/navigation";
import { API_BASE_URL, artifactUrl, type JobResponse } from "../../../../../../lib/api";

type PageProps = {
  params: Promise<{ jobId: string; artifactId: string }>;
};

export default async function ArtifactPreviewPage({ params }: PageProps) {
  const { jobId, artifactId } = await params;
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`, { cache: "no-store" });
  if (!response.ok) {
    notFound();
  }
  const job = (await response.json()) as JobResponse;
  const artifact = job.artifacts.find((item) => item.artifact_id === artifactId);
  if (!artifact) {
    notFound();
  }

  const sourceUrl = artifactUrl(artifactId);
  const isPdf = artifact.mime_type === "application/pdf";
  const isJson = artifact.mime_type.includes("json");

  return (
    <div className="marketing-shell workbench-shell">
      <section className="inner-hero workbench-hero">
        <span className="eyebrow">Artifact Preview</span>
        <h1>{artifact.kind}</h1>
        <p className="hero-text">{artifact.path}</p>
        <div className="hero-actions">
          <Link className="button-ghost" href={`/workbench/jobs/${jobId}`}>
            Back to Job
          </Link>
          <a className="button-primary" href={sourceUrl} target="_blank" rel="noreferrer">
            Download Artifact
          </a>
        </div>
      </section>

      {isPdf ? (
        <iframe className="preview-frame" src={sourceUrl} title={artifact.kind} />
      ) : isJson ? (
        <pre className="code-block">
          {await (await fetch(sourceUrl, { cache: "no-store" })).text()}
        </pre>
      ) : (
        <div className="marketing-card">
          <p>No rich preview is available for this artifact type yet.</p>
          <a className="button-ghost" href={sourceUrl} target="_blank" rel="noreferrer">
            Open File
          </a>
        </div>
      )}
    </div>
  );
}
