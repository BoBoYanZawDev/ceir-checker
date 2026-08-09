import { ceirJsonError, withCeirSession } from "@/lib/server/ceir-browser";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const { declarationId } = await request.json() as { declarationId?: string };
    if (!declarationId) return Response.json({ ok: false, error: "Declaration ID is required." }, { status: 400 });
    const result = await withCeirSession(async (session) => {
      const token = await session.altcha();
      const response = await session.fetch(session.page, `/openapi/API/IMEI/RegistrationStatus?DeclarationID=${encodeURIComponent(declarationId)}&altcha=${encodeURIComponent(token)}`);
      if (!response.ok) throw new Error(`Registration Status returned HTTP ${response.status}.`);
      const data = JSON.parse(response.text) as Record<string, unknown>;
      const status = (data.RequestStatus && typeof data.RequestStatus === "object" ? data.RequestStatus : data) as Record<string, unknown>;
      return { businessState: String(status.BusinessState ?? status.businessState ?? "UNKNOWN").toUpperCase(), status };
    });
    return Response.json({ ok: true, ...result });
  } catch (error) {
    return ceirJsonError(error);
  }
}
