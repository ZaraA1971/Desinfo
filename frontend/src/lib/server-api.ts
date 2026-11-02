import type {
  GovSnapshot,
  MetaResponse,
  RankingKind,
  RankingSnapshot,
} from "@/lib/api";

function apiBase(): string {
  const host = process.env.DESINFO_API_HOST || "127.0.0.1";
  const port = process.env.DESINFO_API_PORT || "8700";
  return `http://${host}:${port}`;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    next: { revalidate: 3600 },
  });
  if (!res.ok) {
    throw new Error(`${path} unavailable (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export async function loadMeta(): Promise<MetaResponse> {
  return getJson<MetaResponse>("/api/meta");
}

export async function loadRanking(
  windowKey: string,
  kind: RankingKind,
): Promise<RankingSnapshot> {
  const q = new URLSearchParams({ window: windowKey, kind });
  return getJson<RankingSnapshot>(`/api/ranking?${q}`);
}

export async function loadGov(): Promise<GovSnapshot> {
  return getJson<GovSnapshot>("/api/gov");
}

export type HomeInitialData = {
  kind: "media" | "politicians" | "gov";
  windowKey: string;
  meta: MetaResponse | null;
  snap: RankingSnapshot | null;
  govSnap: GovSnapshot | null;
  error: string | null;
};

export async function loadHomeInitial(sp: {
  kind?: string;
  window?: string;
}): Promise<HomeInitialData> {
  const kind =
    sp.kind === "politicians" || sp.kind === "gov" ? sp.kind : "media";
  const windowKey = ["7d", "30d", "90d", "365d"].includes(sp.window || "")
    ? (sp.window as string)
    : "7d";

  try {
    const meta = await loadMeta();
    if (kind === "gov") {
      const govSnap = await loadGov();
      return { kind, windowKey, meta, snap: null, govSnap, error: null };
    }
    const statusMap =
      kind === "politicians"
        ? meta.politicians_windows_status
        : meta.windows_status;
    let effectiveWindow = windowKey;
    const st = statusMap?.[windowKey as keyof typeof statusMap];
    if (windowKey !== "7d" && st && !st.available) {
      effectiveWindow = "7d";
    }
    const snap = await loadRanking(
      effectiveWindow,
      kind === "politicians" ? "politicians" : "media",
    );
    return {
      kind,
      windowKey: effectiveWindow,
      meta,
      snap,
      govSnap: null,
      error: null,
    };
  } catch (e) {
    return {
      kind,
      windowKey,
      meta: null,
      snap: null,
      govSnap: null,
      error: e instanceof Error ? e.message : "Erreur de chargement",
    };
  }
}
