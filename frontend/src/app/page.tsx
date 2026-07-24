"use client";

import { Suspense, useEffect, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ExportPanel } from "@/components/ExportPanel";
import { RankingTable } from "@/components/RankingTable";
import {
  MetaResponse,
  RankingKind,
  RankingSnapshot,
  WINDOWS,
  WindowKey,
  WindowStatus,
  fetchMeta,
  fetchRanking,
} from "@/lib/api";

function windowTitle(w: WindowKey, st: WindowStatus | undefined): string {
  if (!st) return w;
  if (st.available) {
    return st.metric_mode === "post_cn" ? "CN/Post disponible" : "CN only";
  }
  if (w === "7d") return w;
  const pct = Math.round((st.progress ?? 0) * 100);
  return `${w} — en cours (${pct} %) · se remplit par moisson hebdo`;
}

function parseKind(raw: string | null): RankingKind {
  return raw === "politicians" ? "politicians" : "media";
}

function parseWindow(raw: string | null, fallback = "7d"): string {
  if (raw && (WINDOWS as readonly string[]).includes(raw)) return raw;
  return fallback;
}

function HomePageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const kind = parseKind(searchParams.get("kind"));
  const windowKey = parseWindow(searchParams.get("window"), "7d");

  const [snap, setSnap] = useState<RankingSnapshot | null>(null);
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const replaceParams = (next: { kind?: RankingKind; window?: string }) => {
    const params = new URLSearchParams(searchParams.toString());
    const nextKind = next.kind ?? kind;
    const nextWindow = next.window ?? windowKey;

    if (nextKind === "media") params.delete("kind");
    else params.set("kind", nextKind);

    if (nextWindow === "7d") params.delete("window");
    else params.set("window", nextWindow);

    const q = params.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
  };

  useEffect(() => {
    startTransition(() => {
      (async () => {
        try {
          setError(null);
          setSnap(null);
          const m = await fetchMeta();
          setMeta(m);
          const statusMap =
            kind === "politicians"
              ? m.politicians_windows_status
              : m.windows_status;
          let effectiveWindow = windowKey;
          const st = statusMap?.[windowKey as WindowKey];
          if (windowKey !== "7d" && st && !st.available) {
            effectiveWindow = "7d";
            replaceParams({ window: "7d" });
          }
          const r = await fetchRanking(effectiveWindow, kind);
          setSnap(r);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Erreur de chargement");
        }
      })();
    });
  }, [windowKey, kind]);

  const onKindChange = (next: RankingKind) => {
    if (next === kind) return;
    replaceParams({ kind: next });
  };

  const onWindowChange = (w: string) => {
    if (w === windowKey) return;
    replaceParams({ window: w });
  };

  const generated = snap?.generated_at
    ? new Date(snap.generated_at).toLocaleString("fr-FR", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";

  const nextHarvest = meta?.next_x_sync_at
    ? new Date(meta.next_x_sync_at).toLocaleDateString("fr-FR", {
        weekday: "short",
        day: "numeric",
        month: "short",
      })
    : null;

  const statusMap =
    kind === "politicians"
      ? meta?.politicians_windows_status
      : meta?.windows_status;
  const ready =
    (kind === "politicians"
      ? meta?.politicians_windows_ready
      : meta?.windows_ready) || {};
  const activeWindowAvailable =
    windowKey === "7d" || statusMap?.[windowKey as WindowKey]?.available !== false;

  return (
    <main className="shell">
      <h1 className="brand">Observatoire de la désinformation</h1>
      <p className="lede">
        Palmarès roulant fondé sur les Community Notes jugées utiles sur X.
        Classement principal par densité de notes :{" "}
        <strong>CN / Posts</strong>.
      </p>

      <div className="kind-tabs" role="tablist" aria-label="Périmètre">
        <button
          type="button"
          role="tab"
          aria-selected={kind === "media"}
          className={kind === "media" ? "is-active" : ""}
          onClick={() => onKindChange("media")}
        >
          Médias
          {meta ? ` (${meta.roster_size})` : ""}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={kind === "politicians"}
          className={kind === "politicians" ? "is-active" : ""}
          onClick={() => onKindChange("politicians")}
        >
          Candidats 2027
          {meta?.politicians_roster_size != null
            ? ` (${meta.politicians_roster_size})`
            : ""}
        </button>
      </div>

      {kind === "politicians" && (
        <p className="kind-hint">
          Uniquement les candidats déclarés à l’élection présidentielle 2027.
          Attribution via mentions / @handles dans les notes (pas de lookup
          tweet).
        </p>
      )}

      <div className="toolbar">
        <div className="windows" role="group" aria-label="Fenêtre">
          {WINDOWS.map((w: WindowKey) => {
            const st = statusMap?.[w];
            const available = w === "7d" || st?.available === true;
            const mode = ready[w] || st?.metric_mode || "cn_only";
            return (
              <button
                key={w}
                type="button"
                className={!available ? "is-pending" : ""}
                aria-pressed={windowKey === w}
                aria-disabled={!available}
                disabled={!available}
                title={windowTitle(w, st)}
                onClick={() => available && onWindowChange(w)}
              >
                {w}
                {available && mode === "post_cn" ? " ✓" : ""}
              </button>
            );
          })}
        </div>
        <p className="meta-line">
          Calculé le {generated}
          {nextHarvest ? ` · moisson ${nextHarvest}` : ""}
          {pending ? " · mise à jour…" : ""}
          {snap && (
            <span className="badge">
              {snap.metric_mode === "post_cn" ? "CN/Post" : "CN only"}
            </span>
          )}
        </p>
      </div>

      {error && <p className="error">{error}</p>}
      {!error && snap && (
        <RankingTable
          items={snap.items}
          metricMode={snap.metric_mode}
          entityLabel={kind === "politicians" ? "Candidat" : "Média"}
          showRadar={kind === "media"}
        />
      )}
      {!error && !snap && !pending && (
        <p className="empty">Chargement du palmarès…</p>
      )}

      {!error && snap && activeWindowAvailable && windowKey && (
        <ExportPanel windowKey={windowKey} kind={kind} />
      )}

      <section className="method" id="methodologie">
        <h2>Méthodologie</h2>
        <p>
          Source : dump public Community Notes (X). Seules les notes au statut{" "}
          <em>CURRENTLY_RATED_HELPFUL</em> sont retenues.
        </p>
        <p>
          <strong>Médias</strong> : attribution via domaines d’URL dans le texte
          des notes. <strong>Candidats</strong> : attribution via @handles et
          noms/aliases déclarés dans le roster souverain.
        </p>
        <p>
          Métrique principale : <strong>CN / Posts</strong>. Fenêtre par défaut
          : 7 jours (médias et candidats). Les fenêtres 30/90/365 se
          remplissent semaine par semaine par cascade (sans API X) ; elles
          restent grisées jusqu’à couverture suffisante (~70 % du roster).
        </p>
        <p>
          Profil thématique (médias) : radar à 8 axes (politique, santé,
          économie, justice, international, science, technologie, faits
          divers). Longueur des branches proportionnelle au nombre de CN du
          média sur chaque thème. Classification LLM en fin de moisson hebdomadaire.
        </p>
        {meta && (
          <p>
            Roster médias : {meta.roster_size}
            {meta.politicians_roster_size != null
              ? ` · candidats : ${meta.politicians_roster_size}`
              : ""}
            .
          </p>
        )}
      </section>

      <footer>
        Accès libre · Electron Libre ·{" "}
        <a href="https://desinfo.electronlibre.info">
          desinfo.electronlibre.info
        </a>
      </footer>
    </main>
  );
}

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <main className="shell">
          <h1 className="brand">Observatoire de la désinformation</h1>
          <p className="empty">Chargement…</p>
        </main>
      }
    >
      <HomePageInner />
    </Suspense>
  );
}
