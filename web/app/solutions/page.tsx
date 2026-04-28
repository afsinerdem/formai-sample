import { MarketingPage } from "../../components/marketing-page";

export default function SolutionsPage() {
  return (
    <MarketingPage
      eyebrow="Solutions"
      title="Designed for teams where forms slow down operations."
      intro="FormAI fits document-heavy workflows where blank templates, manual data entry, and ambiguous submissions create operational drag."
      sections={[
        {
          title: "Insurance and claims",
          body: "Turn static claim forms into fillable assets and parse completed submissions into structured review-ready data.",
        },
        {
          title: "HR and onboarding",
          body: "Automate packet intake, employee form completion, and structured extraction without losing manual oversight.",
        },
        {
          title: "Compliance operations",
          body: "Handle approvals, inspections, and internal forms with audit-friendly confidence and issue reporting.",
        },
        {
          title: "Sensitive internal workflows",
          body: "Use local OCR positioning for teams that need controlled environments or stricter data handling narratives.",
        },
      ]}
    />
  );
}
