"use client";

import { Suspense, useEffect, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ExportPanel } from "@/components/ExportPanel";
import { GovMeasures } from "@/components/GovMeasures";
import { RankingTable } from "@/components/RankingTable";
import {
  GovSnapshot,
  MetaResponse,
  PageKind,
  RankingKind,
  RankingSnapshot,
  WINDOWS,
  WindowKey,
  WindowStatus,
  fetchGov,
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

function parseKind(raw: string | null): PageKind {
  if (raw === "politicians") return "politicians";
  if (raw === "gov") return "gov";
  return "media";
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
  const [govSnap, setGovSnap] = useState<GovSnapshot | null>(null);
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const replaceParams = (next: { kind?: PageKind; window?: string }) => {
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
          setGovSnap(null);
          const m = await fetchMeta();
          setMeta(m);
          if (kind === "gov") {
            setGovSnap(await fetchGov());
            return;
          }
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
          const r = await fetchRanking(
            effectiveWindow,
            kind === "politicians" ? "politicians" : "media",
          );
          setSnap(r);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Erreur de chargement");
        }
      })();
    });
  }, [windowKey, kind]);

  const onKindChange = (next: PageKind) => {
    if (next === kind) return;
    replaceParams({ kind: next });
  };

  const onWindowChange = (w: string) => {
    if (w === windowKey) return;
    replaceParams({ window: w });
  };

  const generatedSource =
    kind === "gov" ? govSnap?.generated_at : snap?.generated_at;
  const generated = generatedSource
    ? new Date(generatedSource).toLocaleString("fr-FR", {
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
        <button
          type="button"
          role="tab"
          aria-selected={kind === "gov"}
          className={kind === "gov" ? "is-active" : ""}
          onClick={() => onKindChange("gov")}
        >
          Demandes des États
          {meta?.gov_measure_count != null ? ` (${meta.gov_measure_count})` : ""}
        </button>
      </div>

      {kind === "politicians" && (
        <p className="kind-hint">
          Uniquement les candidats déclarés à l’élection présidentielle 2027.
          Attribution via mentions / @handles dans les notes (pas de lookup
          tweet).
        </p>
      )}
      {kind === "gov" && (
        <p className="kind-hint">
          Ce que X a rendu public dans son code. Pas la liste complète des
          posts retirés.
        </p>
      )}

      {kind !== "gov" && (
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
      )}
      {kind === "gov" && (
        <p className="meta-line gov-meta">
          Lu dans le code X le {generated}
          {govSnap ? ` · ${govSnap.account_count} comptes` : ""}
          {pending ? " · mise à jour…" : ""}
        </p>
      )}

      {error && <p className="error">{error}</p>}
      {!error && kind === "gov" && govSnap && <GovMeasures snap={govSnap} />}
      {!error && kind !== "gov" && snap && (
        <RankingTable
          items={snap.items}
          metricMode={snap.metric_mode}
          entityLabel={kind === "politicians" ? "Candidat" : "Média"}
          showRadar
        />
      )}
      {!error &&
        !pending &&
        ((kind === "gov" && !govSnap) || (kind !== "gov" && !snap)) && (
          <p className="empty">
            {kind === "gov"
              ? "Chargement des demandes des États…"
              : "Chargement du palmarès…"}
          </p>
        )}

      {!error &&
        kind !== "gov" &&
        snap &&
        activeWindowAvailable &&
        windowKey && (
          <ExportPanel
            windowKey={windowKey}
            kind={kind === "politicians" ? "politicians" : "media"}
          />
        )}

      <section className="method" id="methodologie">
        <h2>Méthodologie</h2>
        {kind === "gov" ? (
          <>
            <p>
              Source : le code public de X (
              <a
                href="https://github.com/xai-org/x-algorithm#latest-updates"
                target="_blank"
                rel="noopener noreferrer"
              >
                x-algorithm
              </a>
              ). On lit les filtres que X y publie. On n’appelle pas l’API X
              pour cette page.
            </p>
            <p>
              {govSnap?.disclaimer ||
                "On montre seulement ce que X a mis dans son code public. Ce n’est pas la liste de tous les posts retirés à la demande d’un État."}
            </p>
            <p>
              Un clic sur une ligne ouvre les comptes concernés, tels qu’ils
              apparaissent dans le fichier source.
            </p>
          </>
        ) : (
          <>
            <p>
              Source : dump public Community Notes (X). Seules les notes au
              statut <em>CURRENTLY_RATED_HELPFUL</em> sont retenues.
            </p>
            <p>
              <strong>Médias</strong> : attribution via domaines d’URL dans le
              texte des notes. <strong>Candidats</strong> : attribution via
              @handles et noms/aliases déclarés dans le roster souverain.
            </p>
            <p>
              Métrique principale : <strong>CN / Posts</strong>. Fenêtre par
              défaut : 7 jours (médias et candidats). Les fenêtres 30/90/365 se
              remplissent semaine par semaine par cascade (sans API X) ; elles
              restent grisées jusqu’à couverture suffisante (~70 % du roster).
            </p>
            <p>
              Profil thématique (médias et candidats) : radar à 8 axes
              (politique, santé, économie, justice, international, science,
              technologie, faits divers) + compteur discret « (hors radar) ».
              Longueur des branches proportionnelle au nombre de CN sur chaque
              thème. Classification LLM en fin de moisson hebdomadaire.
            </p>
          </>
        )}
      </section>

      <footer>
        <p className="transparency">
          Service critique : code et méthode en accès libre (AGPL), pour que
          chacun puisse vérifier comment le palmarès est produit —{" "}
          <a
            href="https://github.com/ZaraA1971/Desinfo"
            target="_blank"
            rel="noopener noreferrer"
          >
            dépôt GitHub
          </a>
          .
        </p>
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
