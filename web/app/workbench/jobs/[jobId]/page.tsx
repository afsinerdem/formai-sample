import { notFound } from "next/navigation";
import { JobDetail } from "../../../../components/job-detail";
import { API_BASE_URL, type JobResponse } from "../../../../lib/api";

type PageProps = {
  params: Promise<{ jobId: string }>;
};

export default async function JobPage({ params }: PageProps) {
  const { jobId } = await params;
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`, { cache: "no-store" });
  if (!response.ok) {
    notFound();
  }
  const job = (await response.json()) as JobResponse;
  return <JobDetail jobId={jobId} initialJob={job} />;
}
