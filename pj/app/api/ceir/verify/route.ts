import type { ImeiPair } from "@/lib/types";
import { ceirJsonError, withCeirSession } from "@/lib/server/ceir-browser";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type VerifyItem = { IMEI?: string; paymentState?: string; blockState?: string };

export async function POST(request: Request) {
  try {
    const { pairs } = await request.json() as { pairs?: ImeiPair[] };
    if (!Array.isArray(pairs) || pairs.length === 0) return Response.json({ ok: false, error: "No IMEI pairs supplied." }, { status: 400 });
    if (pairs.length > 100) return Response.json({ ok: false, error: "A maximum of 100 devices is allowed per request." }, { status: 400 });

    const results = await withCeirSession(async (session) => {
      const output = [];
      for (let offset = 0; offset < pairs.length; offset += 5) {
        const batch = pairs.slice(offset, offset + 5);
        const imeis = batch.flatMap((pair) => pair.imei2 ? [pair.imei1, pair.imei2] : [pair.imei1]);
        const token = await session.altcha();
        const response = await session.fetch(session.page, `/openapi/API/IMEI/Verify?altcha=${encodeURIComponent(token)}`, { method: "POST", body: JSON.stringify(imeis), headers: { "Content-Type": "application/json" } });
        if (!response.ok) throw new Error(`CEIR IMEI Verify returned HTTP ${response.status}: ${response.text.slice(0, 160)}`);
        const data = JSON.parse(response.text) as { IMEI_CHECK_LIST?: VerifyItem[] };
        const lookup = new Map((data.IMEI_CHECK_LIST ?? []).map((item) => [item.IMEI, item]));
        for (const pair of batch) {
          const first = lookup.get(pair.imei1); const second = pair.imei2 ? lookup.get(pair.imei2) : undefined;
          const block1 = first?.blockState ?? ""; const block2 = second?.blockState ?? "";
          output.push({
            id: `${pair.imei1}-${offset + output.length}`,
            ...pair,
            device: "—",
            payment1: first?.paymentState ?? "FAILED",
            payment2: pair.imei2 ? second?.paymentState ?? "FAILED" : "",
            block: pair.imei2 ? (block1 === "UNBLOCKED" && block2 === "UNBLOCKED" ? "UNBLOCKED" : `${block1}/${block2}`) : block1,
            status: first && (!pair.imei2 || second) ? "OK" : "FAILED",
          });
        }
        if (offset + 5 < pairs.length) await session.page.waitForTimeout(2_000);
      }
      return output;
    });
    return Response.json({ ok: true, results });
  } catch (error) {
    return ceirJsonError(error);
  }
}
