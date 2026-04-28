import Link from "next/link";

type Props = {
  eyebrow: string;
  title: string;
  intro: string;
  sections: Array<{
    title: string;
    body: string;
  }>;
  ctaLabel?: string;
  ctaHref?: string;
};

export function MarketingPage({ eyebrow, title, intro, sections, ctaLabel = "Book Demo", ctaHref = "/demo" }: Props) {
  return (
    <div className="marketing-shell">
      <section className="inner-hero">
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p className="hero-text">{intro}</p>
        <div className="hero-actions">
          <Link className="button-primary" href={ctaHref}>
            {ctaLabel}
          </Link>
          <Link className="button-ghost" href="/workbench">
            Open Workbench
          </Link>
        </div>
      </section>

      <section className="section-block">
        <div className="card-grid two">
          {sections.map((section) => (
            <article key={section.title} className="marketing-card">
              <h2>{section.title}</h2>
              <p>{section.body}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
