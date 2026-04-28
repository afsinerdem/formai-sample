import Link from "next/link";
import { HashScrollManager } from "./hash-scroll-manager";
import { NorthFaq } from "./north-faq";

const workflowSteps = [
  {
    title: "Bring the form in",
    body: "Start with the blank template and the completed version.",
  },
  {
    title: "Make it workable",
    body: "The template becomes a clean, reusable fillable flow.",
  },
  {
    title: "Pull out the details",
    body: "Completed forms become structured information you can actually use.",
  },
  {
    title: "Send out the final result",
    body: "The finished form is assembled and ready to review or share.",
  },
];

const capabilityStats = [
  { value: "Blank in", label: "No redesign", detail: "Use the forms you already have" },
  { value: "Clean out", label: "Better outputs", detail: "Fillable PDF + final packet" },
  { value: "Review built in", label: "Human checks", detail: "Confidence stays visible" },
  { value: "Cloud or local", label: "Your choice", detail: "Convenience or privacy-first" },
];

const deploymentModes = [
  {
    title: "Managed cloud",
    eyebrow: "OpenAI-backed",
    body: "A fast path for teams that want the easiest rollout and the least setup work.",
  },
  {
    title: "Private local",
    eyebrow: "GLM / Ollama-backed",
    body: "A privacy-first path for sensitive workflows, local control, and tighter data handling.",
  },
];

const useCases = [
  "Insurance intake",
  "HR onboarding",
  "Compliance ops",
  "Sensitive back-office workflows",
];

const faqItems = [
  {
    question: "Is FormAI a product or an add-on?",
    answer: "It works best as an add-on for teams that already deal with form-heavy operations and want a cleaner intake layer.",
  },
  {
    question: "Can we position local processing for sensitive documents?",
    answer: "Yes. FormAI can be shown with a private local path for teams that care about controlled environments and tighter data handling.",
  },
  {
    question: "Do people still get a chance to review the output?",
    answer: "Yes. Review cues and confidence stay visible so the workflow still feels accountable.",
  },
];

export function MarketingHome() {
  return (
    <div className="north-home">
      <HashScrollManager />
      <section className="north-panel" id="top">
        <div className="marketing-shell north-panel-inner north-hero-grid">
          <div className="north-hero-copy">
            <span className="eyebrow">Enterprise form automation add-on</span>
            <h1 className="north-headline">Turn blank forms into fast, clean workflows.</h1>
            <p className="north-subtitle">
              FormAI helps teams move from flat forms and manual re-entry to a cleaner intake experience that actually
              feels manageable.
            </p>
            <div className="hero-actions">
              <Link className="button-primary" href="/demo">
                Book Demo
              </Link>
              <Link className="button-ghost" href="/workbench">
                Open Workbench
              </Link>
            </div>
            <p className="north-microcopy">
              Choose a managed cloud path or a private local path for more sensitive workflows.
            </p>
          </div>

          <aside className="north-rail">
            <div className="north-rail-card north-rail-dark">
              <span className="north-rail-label">Pipeline</span>
              <strong>One form flow. Four simple steps.</strong>
              <ul className="north-mini-steps">
                {workflowSteps.map((step, index) => (
                  <li key={step.title}>
                    <span>{index + 1}</span>
                    <div>
                      <strong>{step.title}</strong>
                      <p>{step.body}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </aside>
        </div>
      </section>

      <section className="north-panel" id="how-it-works">
        <div className="marketing-shell north-panel-inner">
          <div className="north-stat-strip">
            {capabilityStats.map((item) => (
              <article key={item.label} className="north-stat">
                <strong>{item.value}</strong>
                <span>{item.label}</span>
                <small>{item.detail}</small>
              </article>
            ))}
          </div>

          <div className="north-section-intro">
            <span className="eyebrow">How it works</span>
            <h2>From static form to final result.</h2>
          </div>
          <div className="north-process-grid">
            {workflowSteps.map((step, index) => (
              <article key={step.title} className="north-process-step">
                <span>{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="north-panel" id="before-after">
        <div className="marketing-shell north-panel-inner">
          <div className="north-section-intro north-section-intro-centered">
            <span className="eyebrow">Before & after</span>
            <h2>Less chasing. More flow.</h2>
            <p className="north-section-copy">
              Before FormAI, the work gets split across emails, copy-paste, and final clean-up. With FormAI, the same
              form moves through one calmer flow.
            </p>
          </div>

          <div className="north-before-after">
            <article className="north-journey-card north-journey-old">
              <span className="north-journey-label">Before FormAI</span>
              <div className="north-flow north-flow-old">
                <div className="north-flow-column">
                  <span className="north-flow-kicker">Template</span>
                  <div className="north-flow-pill north-flow-pill-dark">Flat PDF</div>
                </div>
                <div className="north-flow-arrow-stack" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <div className="north-flow-column north-flow-column-wide">
                  <div className="north-flow-box north-flow-box-muted">Email back-and-forth</div>
                  <div className="north-flow-box north-flow-box-muted">Manual re-entry</div>
                  <div className="north-flow-box north-flow-box-muted">Last-minute cleanup</div>
                </div>
              </div>
              <div className="north-mobile-compare" aria-hidden="true">
                <div className="north-mobile-compare-row">
                  <span className="north-mobile-compare-tag">Start</span>
                  <strong>Flat PDF</strong>
                </div>
                <div className="north-mobile-compare-stack north-mobile-compare-stack-muted">
                  <div>Email back-and-forth</div>
                  <div>Manual re-entry</div>
                  <div>Last-minute cleanup</div>
                </div>
              </div>
              <div className="north-journey-footer north-journey-footer-muted">
                Slow, repetitive, and easy to lose track of.
              </div>
            </article>

            <div className="north-versus">vs.</div>

            <article className="north-journey-card north-journey-new">
              <span className="north-journey-label">With FormAI</span>
              <div className="north-flow north-flow-new">
                <div className="north-flow-column">
                  <span className="north-flow-kicker north-flow-kicker-accent">Inputs</span>
                  <div className="north-flow-pill north-flow-pill-accent">Blank template</div>
                  <div className="north-flow-pill north-flow-pill-accent">Completed form</div>
                </div>
                <div className="north-flow-center" aria-hidden="true">
                  <span>F</span>
                </div>
                <div className="north-flow-column north-flow-column-wide">
                  <div className="north-flow-box north-flow-box-accent">Fillable PDF</div>
                  <div className="north-flow-box north-flow-box-accent">Structured data</div>
                  <div className="north-flow-box north-flow-box-accent">Final packet</div>
                </div>
              </div>
              <div className="north-mobile-compare" aria-hidden="true">
                <div className="north-mobile-compare-row">
                  <span className="north-mobile-compare-tag north-mobile-compare-tag-accent">Inputs</span>
                  <strong>Blank template + completed form</strong>
                </div>
                <div className="north-mobile-compare-stack north-mobile-compare-stack-accent">
                  <div>Fillable PDF</div>
                  <div>Structured data</div>
                  <div>Final packet</div>
                </div>
              </div>
              <div className="north-journey-footer north-journey-footer-accent">
                One cleaner flow from intake to final output.
              </div>
            </article>
          </div>
        </div>
      </section>

      <section className="north-panel" id="privacy">
        <div className="marketing-shell north-panel-inner">
          <div className="north-section-intro">
            <span className="eyebrow">Privacy</span>
            <h2>Choose the setup that fits the workflow.</h2>
            <p className="north-section-copy">
              Some teams want the fastest path. Others need a more private local story. FormAI supports both without
              changing the core experience.
            </p>
          </div>

          <div className="north-compare-grid north-compare-grid-tight">
            {deploymentModes.map((mode) => (
              <article key={mode.title} className="north-compare-card">
                <span className="chip">{mode.eyebrow}</span>
                <h3>{mode.title}</h3>
                <p>{mode.body}</p>
              </article>
            ))}
          </div>

          <div className="north-proof-grid">
            <article className="north-proof-card">
              <span className="eyebrow">Trust</span>
              <h3>Review stays visible.</h3>
              <p>The workflow stays human-readable, so teams can move faster without feeling blind.</p>
            </article>
            <article className="north-proof-card">
              <span className="eyebrow">Good fit for</span>
              <ul className="north-inline-list">
                {useCases.map((useCase) => (
                  <li key={useCase}>{useCase}</li>
                ))}
              </ul>
            </article>
          </div>
        </div>
      </section>

      <section className="north-panel" id="faq">
        <div className="marketing-shell north-panel-inner">
          <div className="north-section-intro">
            <span className="eyebrow">A clean product surface</span>
            <h2>Simple to explain. Strong enough to run.</h2>
            <p className="north-section-copy">
              The product story stays simple: cleaner form intake, clearer outputs, and a deployment choice that fits
              the team.
            </p>
          </div>

          <div className="north-workbench-preview">
            <div className="north-preview-header">
              <span />
              <span />
              <span />
              <strong>FormAI Workbench</strong>
            </div>
            <div className="north-preview-body">
              <div>
                <small>Inputs</small>
                <strong>Template + completed form</strong>
              </div>
              <div>
                <small>OCR mode</small>
                <strong>Managed or local</strong>
              </div>
              <div>
                <small>Review</small>
                <strong>Clear confidence and review cues</strong>
              </div>
              <div>
                <small>Outputs</small>
                <strong>Fillable PDF, extracted data, final form</strong>
              </div>
            </div>
          </div>

          <div className="north-footer-band">
            <div>
              <span className="eyebrow">Positioning</span>
              <p>
                FormAI is a premium add-on for teams that want form intake to feel calmer, cleaner, and more reliable.
              </p>
            </div>
            <NorthFaq items={faqItems} />
          </div>

          <div className="north-final-cta">
            <h2>See how FormAI fits your workflow.</h2>
            <div className="hero-actions">
              <Link className="button-primary" href="/demo">
                Book Demo
              </Link>
              <Link className="button-ghost" href="/workbench">
                Open Workbench
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
