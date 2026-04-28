import { DemoForm } from "../../components/demo-form";

export default function DemoPage() {
  return (
    <div className="marketing-shell">
      <section className="inner-hero">
        <span className="eyebrow">Book Demo</span>
        <h1>Tell us how your team handles form intake today.</h1>
        <p className="hero-text">
          Use this page as the main conversion endpoint for the marketing site. The form stores structured lead data
          locally so the flow is complete even without a CRM integration.
        </p>
      </section>
      <section className="section-block">
        <div className="card-grid two uneven">
          <article className="marketing-card jumbo">
            <h2>What we’ll show in a demo</h2>
            <ul className="feature-list">
              <li>Blank template to fillable PDF conversion</li>
              <li>Managed OpenAI OCR vs private local OCR positioning</li>
              <li>Review items, confidence, and final PDF assembly</li>
              <li>API and workbench flow for your internal team</li>
            </ul>
          </article>
          <article className="marketing-card">
            <h2>Request a demo</h2>
            <DemoForm />
          </article>
        </div>
      </section>
    </div>
  );
}
