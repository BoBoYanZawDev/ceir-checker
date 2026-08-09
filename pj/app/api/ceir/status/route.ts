import { ceirHealth, ceirJsonError } from "@/lib/server/ceir-browser";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const forceReload = new URL(request.url).searchParams.get("reload") === "1";
    return Response.json(await ceirHealth(forceReload));
  } catch (error) {
    return ceirJsonError(error);
  }
}
