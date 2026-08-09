import { ceirJsonError, withCeirSession } from "@/lib/server/ceir-browser";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const declarationId = new URL(request.url).searchParams.get("declarationId");
    if (!declarationId) return Response.json({ ok: false, error: "Declaration ID is required." }, { status: 400 });
    const html = await withCeirSession(async (session) => {
      const statusToken = await session.altcha();
      const statusResponse = await session.fetch(session.page, `/openapi/API/IMEI/RegistrationStatus?DeclarationID=${encodeURIComponent(declarationId)}&altcha=${encodeURIComponent(statusToken)}`);
      if (!statusResponse.ok) throw new Error(`Registration Status returned HTTP ${statusResponse.status}.`);
      const parsed = JSON.parse(statusResponse.text) as Record<string, unknown>;
      const status = (parsed.RequestStatus && typeof parsed.RequestStatus === "object" ? parsed.RequestStatus : parsed) as Record<string, unknown>;
      const declarationHash = String(status.declarationHash ?? status.DeclarationHash ?? "");
      if (!declarationHash) throw new Error("CEIR response did not include a declaration hash.");

      await session.fetch(session.page, `/openapi/API/phub/payment-check-result?declarationHash=${encodeURIComponent(declarationHash)}&altcha=null`);
      const applicant = await session.fetch(session.page, `/openapi/API/request/applicant?declarationHash=${encodeURIComponent(declarationHash)}&altcha=null`);
      if (!applicant.ok) throw new Error(`Applicant fetch returned HTTP ${applicant.status}.`);
      const paymentToken = await session.altcha();
      const payment = await session.fetch(session.page, `/openapi/API/phub/payment?declarationHash=${encodeURIComponent(declarationHash)}&altcha=${encodeURIComponent(paymentToken)}`, { method: "POST", body: applicant.text, headers: { "Content-Type": "application/json" } });
      if (!payment.ok || payment.text.trim().length < 20) throw new Error(`Payment initialization returned HTTP ${payment.status}.`);
      const inject = '<base href="https://ceir.gov.mm/"><meta name="viewport" content="width=device-width, initial-scale=1">';
      return /<head[^>]*>/i.test(payment.text) ? payment.text.replace(/<head[^>]*>/i, `$&${inject}`) : inject + payment.text;
    });
    return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
  } catch (error) {
    return ceirJsonError(error);
  }
}
