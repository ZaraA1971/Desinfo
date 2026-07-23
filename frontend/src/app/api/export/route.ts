import { createHmac } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { WINDOWS } from "@/lib/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ALLOWED_ORIGINS = new Set([
  "https://desinfo.electronlibre.info",
  "http://127.0.0.1:8710",
  "http://localhost:8710",
]);

const EMAIL_RE = /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/;
const WINDOW_SET = new Set<string>(WINDOWS);

type Body = {
  email?: string;
  window?: string;
  kind?: string;
  consent?: boolean;
  website?: string;
};

function clientIp(req: NextRequest): string {
  const real = (req.headers.get("x-real-ip") || "").trim();
  if (real) return real.slice(0, 64);
  const forwarded = req.headers.get("x-forwarded-for") || "";
  if (forwarded) return forwarded.split(",")[0].trim().slice(0, 64);
  return "unknown";
}

function originOk(req: NextRequest): boolean {
  const origin = (req.headers.get("origin") || "").trim();
  if (origin && ALLOWED_ORIGINS.has(origin)) return true;
  const referer = (req.headers.get("referer") || "").trim();
  if (!referer) return false;
  try {
    const u = new URL(referer);
    return ALLOWED_ORIGINS.has(`${u.protocol}//${u.host}`);
  } catch {
    return false;
  }
}

function sign(
  secret: string,
  ts: string,
  email: string,
  window: string,
  ip: string,
  kind: string,
): string {
  const msg = `${ts}\n${email}\n${window}\n${ip}\n${kind}`;
  return createHmac("sha256", secret).update(msg, "utf8").digest("hex");
}

export async function POST(req: NextRequest) {
  if (!originOk(req)) {
    return NextResponse.json({ detail: "Origine non autorisée" }, { status: 403 });
  }

  let body: Body;
  try {
    body = (await req.json()) as Body;
  } catch {
    return NextResponse.json({ detail: "JSON invalide" }, { status: 400 });
  }

  // Honeypot — bots often fill hidden fields
  if ((body.website || "").trim()) {
    return NextResponse.json({ detail: "Requête rejetée" }, { status: 400 });
  }

  if (!body.consent) {
    return NextResponse.json({ detail: "Le consentement est obligatoire" }, { status: 400 });
  }

  const email = (body.email || "").trim().toLowerCase();
  if (!email || email.length > 254 || !EMAIL_RE.test(email)) {
    return NextResponse.json({ detail: "Adresse e-mail invalide" }, { status: 400 });
  }

  const window = (body.window || "7d").trim().toLowerCase();
  if (!WINDOW_SET.has(window)) {
    return NextResponse.json({ detail: "Fenêtre invalide" }, { status: 400 });
  }

  const kind = (body.kind || "media").trim().toLowerCase();
  if (kind !== "media" && kind !== "politicians") {
    return NextResponse.json({ detail: "Kind invalide" }, { status: 400 });
  }

  const secret = process.env.DESINFO_EXPORT_HMAC_SECRET || "";
  if (!secret) {
    return NextResponse.json({ detail: "Export indisponible" }, { status: 503 });
  }

  const ip = clientIp(req);
  const ts = String(Math.floor(Date.now() / 1000));
  const sig = sign(secret, ts, email, window, ip, kind);

  const apiHost = process.env.DESINFO_API_HOST || "127.0.0.1";
  const apiPort = process.env.DESINFO_API_PORT || "8700";
  const upstream = `http://${apiHost}:${apiPort}/api/export`;

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(upstream, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Real-IP": ip,
        "X-Forwarded-For": ip,
        "X-Desinfo-Export-Ts": ts,
        "X-Desinfo-Export-Sig": sig,
        "User-Agent": req.headers.get("user-agent") || "desinfo-next-export",
      },
      body: JSON.stringify({ email, window, kind, consent: true }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "Service export indisponible" }, { status: 502 });
  }

  if (!upstreamRes.ok) {
    let detail = `Export impossible (${upstreamRes.status})`;
    try {
      const j = (await upstreamRes.json()) as { detail?: string };
      if (typeof j?.detail === "string") detail = j.detail;
    } catch {
      /* ignore */
    }
    return NextResponse.json({ detail }, { status: upstreamRes.status });
  }

  const pdf = await upstreamRes.arrayBuffer();
  const cd =
    upstreamRes.headers.get("Content-Disposition") ||
    `attachment; filename="desinfo_${window}.pdf"`;

  return new NextResponse(pdf, {
    status: 200,
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": cd,
      "Cache-Control": "no-store",
    },
  });
}
