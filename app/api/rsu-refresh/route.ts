import { NextRequest, NextResponse } from "next/server";
import { fetchFastApi } from "@/lib/fastapi-proxy";

export async function POST(req: NextRequest) {
  let tickers: string[] = [];
  try {
    const body = await req.json();
    if (Array.isArray(body?.tickers)) {
      tickers = body.tickers.map(String);
    }
  } catch {
    /* empty body ok */
  }
  const { ok, status, data } = await fetchFastApi("/rsu-refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tickers }),
  });
  return NextResponse.json(data, { status: ok ? 200 : status });
}
