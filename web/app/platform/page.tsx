import { MarketingPage } from "../../components/marketing-page";

export default function PlatformPage() {
  return (
    <MarketingPage
      eyebrow="Platform"
      title="FormAI is the execution layer behind structured form operations."
      intro="Build fillable PDFs, extract structured data, and assemble final forms from one pipeline with reviewable AI output."
      sections={[
        {
          title: "Template intelligence",
          body: "Analyze static PDFs, infer fields from flat layouts, and normalize them into fillable form structures without manual renaming work.",
        },
        {
          title: "Extraction that stays reviewable",
          body: "Every run can surface confidence, issues, mappings, and review items so operators can keep control of risky form fields.",
        },
        {
          title: "Async job orchestration",
          body: "The job-based API and workbench expose the same pipeline as a stable service surface for internal teams and add-on workflows.",
        },
        {
          title: "Deployment choice",
          body: "Position managed OpenAI OCR for velocity and local GLM / Ollama for privacy-sensitive form processing.",
        },
      ]}
    />
  );
}
