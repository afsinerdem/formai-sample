import Link from "next/link";

export default function PricingPage() {
  return (
    <div className="marketing-shell">
      <section className="inner-hero">
        <span className="eyebrow">Pricing</span>
        <h1>Enterprise add-on pricing for serious form workflows.</h1>
        <p className="hero-text">
          FormAI is positioned as a workflow add-on for teams that need fillable generation, structured extraction,
          review, and deployment choice. This page should support a demo-led sale, not a commodity OCR pitch.
        </p>
        <div className="hero-actions">
          <Link className="button-primary" href="/demo">
            Book Demo
          </Link>
          <Link className="button-ghost" href="/workbench">
            Open Workbench
          </Link>
        </div>
      </section>

      <section className="pricing-band">
        <article className="pricing-card featured">
          <span className="chip">Core add-on</span>
          <h2>FormAI Platform</h2>
          <p>For teams that want fillable PDF generation, extraction, review items, and API/workbench access.</p>
          <ul className="feature-list">
            <li>Template analysis + fillable PDF generation</li>
            <li>Structured extraction and field mapping</li>
            <li>Confidence scoring and review queue</li>
            <li>Async API jobs and internal workbench</li>
          </ul>
        </article>
        <article className="pricing-card">
          <span className="chip">Privacy add-on</span>
          <h2>Private OCR Deployment</h2>
          <p>For customers that need local GLM / Ollama positioning and a stronger sensitive-data deployment story.</p>
          <ul className="feature-list">
            <li>Local OCR mode</li>
            <li>On-prem / controlled environment narrative</li>
            <li>Security-first deployment alignment</li>
          </ul>
        </article>
        <article className="pricing-card">
          <span className="chip">Services</span>
          <h2>Workflow Design</h2>
          <p>For teams that need implementation help, form family rollout, and operational tuning.</p>
          <ul className="feature-list">
            <li>Template onboarding</li>
            <li>Review workflow design</li>
            <li>Integration and rollout support</li>
          </ul>
        </article>
      </section>
    </div>
  );
}
