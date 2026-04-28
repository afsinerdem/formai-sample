import { MarketingPage } from "../../components/marketing-page";

export default function SecurityPage() {
  return (
    <MarketingPage
      eyebrow="Security"
      title="Security posture starts with deployment choice and human review."
      intro="FormAI should be sold as a controlled workflow layer for sensitive documents, not as opaque automation with no operator visibility."
      sections={[
        {
          title: "Private local OCR",
          body: "Use GLM / Ollama-backed local processing for customers who need a stronger privacy and data-residency story.",
        },
        {
          title: "Managed cloud OCR",
          body: "Use OpenAI-backed workflows when teams prefer faster onboarding and managed accuracy under a cloud delivery model.",
        },
        {
          title: "Human-in-the-loop trust",
          body: "Confidence scoring, review items, and issue reporting help teams spot uncertainty rather than silently over-trusting output.",
        },
        {
          title: "Operational containment",
          body: "Job-based artifact handling keeps large files in controlled paths instead of pushing raw binaries through every response surface.",
        },
      ]}
    />
  );
}
