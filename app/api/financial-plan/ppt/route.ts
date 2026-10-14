import { NextResponse } from "next/server";
import { fetchFastApiBinary } from "@/lib/fastapi-proxy";

export async function POST(req: Request) {
  let body: { workflow_state?: Record<string, unknown> } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const workflow_state = body?.workflow_state;
  if (!workflow_state || typeof workflow_state !== "object") {
    return NextResponse.json(
      { detail: "workflow_state is required" },
      { status: 400 },
    );
  }

  // The 49-slide Goal Based Planning deck (Financial_Planning/PPTX_Migration).
  // The previous deck is still served at /financial-plan/ppt; point this back
  // there to revert.
  const { ok, status, data, contentType, contentDisposition, errorDetail } =
    await fetchFastApiBinary("/financial-plan/ppt-v2", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow_state }),
    });

  if (!ok || !data) {
    return NextResponse.json(
      { detail: errorDetail ?? "PPT generation failed" },
      { status: status || 502 },
    );
  }

  return new NextResponse(data, {
    status: 200,
    headers: {
      "Content-Type":
        contentType ??
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      "Content-Disposition":
        contentDisposition ?? 'attachment; filename="financial_plan.pptx"',
    },
  });
}
