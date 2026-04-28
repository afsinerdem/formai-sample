import { redirect } from "next/navigation";

type PageProps = {
  params: Promise<{ jobId: string }>;
};

export default async function LegacyJobPage({ params }: PageProps) {
  const { jobId } = await params;
  redirect(`/workbench/jobs/${jobId}`);
}
