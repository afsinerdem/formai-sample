import { mkdir, appendFile } from "node:fs/promises";
import { join } from "node:path";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const payload = await request.json().catch(() => null);
  if (!payload || typeof payload !== "object") {
    return NextResponse.json({ error: "Invalid demo request payload." }, { status: 422 });
  }

  const name = String(payload.name || "").trim();
  const workEmail = String(payload.work_email || "").trim();
  const company = String(payload.company || "").trim();
  const message = String(payload.message || "").trim();

  if (!name || !workEmail || !company || !message) {
    return NextResponse.json(
      { error: "Name, work email, company, and workflow context are required." },
      { status: 422 },
    );
  }

  const outputDir = join(process.cwd(), "..", "tmp", "web_demo_leads");
  await mkdir(outputDir, { recursive: true });
  const entry = {
    created_at: new Date().toISOString(),
    name,
    work_email: workEmail,
    company,
    team_size: String(payload.team_size || ""),
    deployment_preference: String(payload.deployment_preference || ""),
    message,
  };
  await appendFile(join(outputDir, "demo_requests.jsonl"), `${JSON.stringify(entry)}\n`, "utf-8");
  return NextResponse.json({ ok: true });
}
