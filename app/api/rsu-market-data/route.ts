import { NextResponse } from "next/server";
import { fetchFastApi } from "@/lib/fastapi-proxy";

export async function GET() {
  const { ok, status, data } = await fetchFastApi("/rsu-market-data");
  return NextResponse.json(data, { status: ok ? 200 : status });
}
