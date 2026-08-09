import type { Applicant, ImeiPair } from "@/lib/types";
import { ceirJsonError, withCeirSession } from "@/lib/server/ceir-browser";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Calculation = { collectingType?: string; amount?: number; conditionPassed?: boolean };

export async function POST(request: Request) {
  try {
    const { pairs, applicant } = await request.json() as { pairs?: ImeiPair[]; applicant?: Applicant };
    if (!Array.isArray(pairs) || pairs.length === 0) return Response.json({ ok: false, error: "No IMEI pairs supplied." }, { status: 400 });
    if (!applicant?.nationalId || !applicant.fullName) return Response.json({ ok: false, error: "National ID and full name are required." }, { status: 400 });
    if (pairs.length > 50) return Response.json({ ok: false, error: "A maximum of 50 registrations is allowed per request." }, { status: 400 });

    const registered = await withCeirSession(async (session) => {
      const rows = [];
      for (let index = 0; index < pairs.length; index += 1) {
        const pair = pairs[index];
        let response: Awaited<ReturnType<typeof session.fetch>> | null = null;
        for (let attempt = 1; attempt <= 3; attempt += 1) {
          const token = await session.altcha();
          const body = JSON.stringify({
            imeisList: [{ imeis: pair.imei2 ? [pair.imei1, pair.imei2] : [pair.imei1] }],
            applicant: {
              id: null, requestId: null, taxpayerType: "Individual", isForeigner: false, tin: null,
              nationalId: applicant.nationalId, fullName: applicant.fullName, birthday: applicant.birthday,
              address: applicant.address, email: applicant.email, phone: applicant.phone,
              taxOfficeDivision: applicant.division, taxOfficeCode: applicant.officeCode,
              regionCode: null, townshipCode: null, uin: null,
            },
          });
          response = await session.fetch(session.page, `/openapi/API/IMEI/RegistrationRequest?source=LEGAL_INDIVIDUAL&altcha=${encodeURIComponent(token)}`, { method: "POST", body, headers: { "Content-Type": "application/json" } });
          const transient = !response.ok && (response.status === 0 || response.status === 403 || response.status >= 500);
          if (!transient || attempt === 3) break;
          await session.page.waitForTimeout(attempt * attempt * 1_000);
        }
        if (!response) throw new Error("CEIR registration returned no response.");
        if (!response.ok && response.status >= 500) throw new Error(`CEIR Registration returned HTTP ${response.status}.`);
        const data = JSON.parse(response.text || "{}") as { HasError?: boolean; Message?: string; message?: string; Registry?: { DeclarationID?: string; amount?: number; orderCalculation?: { collectingCalculations?: Calculation[] } } };
        if (data.HasError || !data.Registry) {
          rows.push({ id: `${pair.imei1}-${index}`, ...pair, declarationId: "—", total: 0, customs: 0, commercial: 0, fine: 0, status: "Failed", printable: false, error: data.Message ?? data.message ?? `HTTP ${response.status}` });
        } else {
          const calculations = new Map((data.Registry.orderCalculation?.collectingCalculations ?? []).filter((item) => item.conditionPassed).map((item) => [item.collectingType, item.amount ?? 0]));
          rows.push({ id: `${pair.imei1}-${index}`, ...pair, declarationId: data.Registry.DeclarationID ?? "—", total: data.Registry.amount ?? 0, customs: calculations.get("CUSTOMS_DUTY") ?? 0, commercial: calculations.get("COMMERCIAL_TAX") ?? 0, fine: calculations.get("REDEMPTION_FINE") ?? 0, status: "Pending", printable: true });
        }
        if (index + 1 < pairs.length) await session.page.waitForTimeout(3_000);
      }
      return rows;
    });
    return Response.json({ ok: true, registered });
  } catch (error) {
    return ceirJsonError(error);
  }
}
