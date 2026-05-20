import { NextRequest, NextResponse } from "next/server";
import { fetchFastApi } from "@/lib/fastapi-proxy";

export async function GET(req: NextRequest) {
  const tickers = req.nextUrl.searchParams.getAll("ticker");
  const path =
    tickers.length > 0
      ? `/rsu/market-data?${tickers.map((t) => `ticker=${encodeURIComponent(t)}`).join("&")}`
      : "/rsu-market-data";
  const { ok, status, data } = await fetchFastApi(path);
  return NextResponse.json(data, { status: ok ? 200 : status });
}

export async function POST(req: NextRequest) {
  let tickers: string[] = req.nextUrl.searchParams.getAll("ticker");
  try {
    const body = await req.json().catch(() => null);
    if (body?.tickers && Array.isArray(body.tickers)) {
      tickers = body.tickers.map(String);
    }
  } catch {
    /* ignore */
  }
  const { ok, status, data } = await fetchFastApi("/rsu-refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tickers }),
  });
  return NextResponse.json(data, { status: ok ? 200 : status });
}
