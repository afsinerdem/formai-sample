import { redirect } from "next/navigation";

type PageProps = {
  params: Promise<{ jobId: string; artifactId: string }>;
};

export default async function LegacyArtifactPage({ params }: PageProps) {
  const { jobId, artifactId } = await params;
  redirect(`/workbench/jobs/${jobId}/artifacts/${artifactId}`);
}
