"use client";

import { useEffect, useState, useTransition } from "react";
import { ExportPanel } from "@/components/ExportPanel";
import { RankingTable } from "@/components/RankingTable";
import {
  MetaResponse,
  RankingKind,
  RankingSnapshot,
  WINDOWS,
  fetchMeta,
  fetchRanking,
} from "@/lib/api";

export default function HomePage() {
  const [kind, setKind] = useState<RankingKind>("media");
  const [windowKey, setWindowKey] = useState<string | null>(null);
  const [snap, setSnap] = useState<RankingSnapshot | null>(null);
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    startTransition(() => {
      (async () => {
        try {
          setError(null);
          if (windowKey === null) {
            const m = await fetchMeta();
            setMeta(m);
            setWindowKey(m.default_window || "7d");
            return;
          }
          const [m, r] = await Promise.all([
            fetchMeta(),
            fetchRanking(windowKey, kind),
          ]);
          setMeta(m);
          setSnap(r);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Erreur de chargement");
        }
      })();
    });
  }, [windowKey, kind]);

  const onKindChange = (next: RankingKind) => {
    if (next === kind) return;
    setSnap(null);
    setKind(next);
    setWindowKey(null);
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

  const ready =
    (kind === "politicians"
      ? meta?.politicians_windows_ready
      : meta?.windows_ready) || {};

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
          {WINDOWS.map((w) => {
            const mode = ready[w] || "cn_only";
            return (
              <button
                key={w}
                type="button"
                aria-pressed={windowKey === w}
                title={
                  mode === "post_cn"
                    ? "CN/Post disponible"
                    : "CN only pour l’instant"
                }
                onClick={() => setWindowKey(w)}
              >
                {w}
                {mode === "post_cn" ? " ✓" : ""}
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
        />
      )}
      {!error && !snap && !pending && (
        <p className="empty">Chargement du palmarès…</p>
      )}

      {!error && snap && windowKey && (
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
          remplissent ensuite par cascade depuis les collectes hebdomadaires.
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
