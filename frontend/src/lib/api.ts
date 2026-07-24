export type RankingKind = "media" | "politicians";

export type RadarAxis = {
  theme: string;
  label: string;
  cn_count: number;
  weight?: number;
};

export type RadarProfile = {
  axes: RadarAxis[];
  direction?: string;
  coverage?: number;
  /** CN tagged « autre » — shown in chips, excluded from radar polygon */
  autre_count?: number;
  /** CN in window, not yet classified by LLM */
  unclassified_count?: number;
  /** Total attributed CN in window (matches ranking cn_count) */
  attributed_count?: number;
};

export type RankingItem = {
  media_id?: string;
  politician_id?: string;
  name: string;
  party?: string | null;
  domains?: string[];
  x_handle: string | null;
  cn_count: number;
  post_count: number | null;
  rate_cn_per_post: number | null;
  ratio_post_per_cn: number | null;
  rank: number;
  delta_rank: number | null;
  radar?: RadarProfile | null;
};

export type MetricMode = "cn_only" | "post_cn";

export type RankingSnapshot = {
  kind?: RankingKind | string;
  generated_at: string;
  window: string;
  window_days: number;
  metric_mode: MetricMode;
  last_ingest_at: string | null;
  roster_size: number;
  items: RankingItem[];
};

export type MetaResponse = {
  default_window: string;
  windows: string[];
  windows_ready?: Record<string, string>;
  politicians_windows_ready?: Record<string, string>;
  windows_status?: Record<string, WindowStatus>;
  politicians_windows_status?: Record<string, WindowStatus>;
  x_sync_windows?: string[];
  next_x_sync_at?: string | null;
  roster_size: number;
  politicians_roster_size?: number;
  roster_generated_at: string | null;
  last_ingest_at: string | null;
  last_snapshot_at: string | null;
  metric_mode: MetricMode | string;
  kinds?: RankingKind[];
};

export type WindowStatus = {
  available: boolean;
  metric_mode?: MetricMode | string | null;
  progress?: number;
  min_days?: number;
  ready_entities?: number;
  roster_size?: number;
};

export const WINDOWS = ["7d", "30d", "90d", "365d"] as const;
export type WindowKey = (typeof WINDOWS)[number];

export function itemKey(item: RankingItem): string {
  return item.politician_id || item.media_id || item.name;
}

export async function fetchRanking(
  window: string,
  kind: RankingKind = "media",
): Promise<RankingSnapshot> {
  const q = new URLSearchParams({
    window,
    kind,
  });
  const res = await fetch(`/api/ranking?${q}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Ranking unavailable (${res.status})`);
  }
  return res.json();
}

export async function fetchMeta(): Promise<MetaResponse> {
  const res = await fetch("/api/meta", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Meta unavailable (${res.status})`);
  }
  return res.json();
}

/** Affichage Post/CN (souvent grand) */
export function formatRatio(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n >= 1000) return n.toFixed(0);
  if (n >= 100) return n.toFixed(1);
  if (n >= 10) return n.toFixed(2);
  return n.toFixed(3);
}

/**
 * Affichage CN/Post — densités typiques ~0.001–0.02.
 * On montre 4 décimales + équivalent en % pour départager.
 */
export function formatCnPerPost(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n === 0) return "0";
  const pct = n * 100;
  if (pct >= 1) return `${n.toFixed(4)} (${pct.toFixed(2)} %)`;
  if (pct >= 0.1) return `${n.toFixed(4)} (${pct.toFixed(3)} %)`;
  return `${n.toFixed(5)} (${pct.toFixed(4)} %)`;
}

export function formatDelta(d: number | null | undefined): string {
  if (d == null) return "";
  if (d === 0) return "=";
  return d > 0 ? `↑${d}` : `↓${Math.abs(d)}`;
}
