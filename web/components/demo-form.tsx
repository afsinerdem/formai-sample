"use client";

import { useState } from "react";

type DemoState = {
  loading: boolean;
  error: string;
  success: string;
};

export function DemoForm() {
  const [state, setState] = useState<DemoState>({ loading: false, error: "", success: "" });

  async function handleSubmit(formData: FormData) {
    setState({ loading: true, error: "", success: "" });
    const payload = Object.fromEntries(formData.entries());
    try {
      const response = await fetch("/api/demo-leads", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result?.error || "Could not submit demo request.");
      }
      setState({
        loading: false,
        error: "",
        success: "Demo request captured. We can now use this page as the demo conversion endpoint.",
      });
    } catch (error) {
      setState({
        loading: false,
        error: error instanceof Error ? error.message : "Could not submit demo request.",
        success: "",
      });
    }
  }

  return (
    <form
      className="demo-form"
      onSubmit={async (event) => {
        event.preventDefault();
        await handleSubmit(new FormData(event.currentTarget));
      }}
    >
      <div className="field-row">
        <label htmlFor="name">Name</label>
        <input id="name" name="name" type="text" required />
      </div>
      <div className="field-row two-up">
        <div>
          <label htmlFor="work_email">Work email</label>
          <input id="work_email" name="work_email" type="email" required />
        </div>
        <div>
          <label htmlFor="company">Company</label>
          <input id="company" name="company" type="text" required />
        </div>
      </div>
      <div className="field-row two-up">
        <div>
          <label htmlFor="team_size">Team size</label>
          <select id="team_size" name="team_size" defaultValue="10-50">
            <option value="1-10">1-10</option>
            <option value="10-50">10-50</option>
            <option value="50-200">50-200</option>
            <option value="200+">200+</option>
          </select>
        </div>
        <div>
          <label htmlFor="deployment_preference">Deployment preference</label>
          <select id="deployment_preference" name="deployment_preference" defaultValue="local">
            <option value="managed">Managed AI OCR</option>
            <option value="local">Private Local OCR</option>
            <option value="hybrid">Hybrid / undecided</option>
          </select>
        </div>
      </div>
      <div className="field-row">
        <label htmlFor="message">What workflow are you trying to automate?</label>
        <textarea id="message" name="message" rows={5} required />
      </div>
      <div className="action-row">
        <button className="button-primary" type="submit" disabled={state.loading}>
          {state.loading ? "Submitting..." : "Book Demo"}
        </button>
      </div>
      {state.error ? <p className="error-text">{state.error}</p> : null}
      {state.success ? <p className="success-text">{state.success}</p> : null}
    </form>
  );
}
