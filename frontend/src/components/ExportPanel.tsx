"use client";

import { FormEvent, useState } from "react";
import type { RankingKind } from "@/lib/api";

type Props = {
  windowKey: string;
  kind?: RankingKind;
};

export function ExportPanel({ windowKey, kind = "media" }: Props) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setOk(false);
    if (!email.trim()) {
      setError("L’e-mail est obligatoire.");
      return;
    }
    if (!consent) {
      setError("Merci d’accepter les conditions d’export.");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          window: windowKey,
          kind,
          consent: true,
          website,
        }),
      });
      if (!res.ok) {
        let detail = `Export impossible (${res.status})`;
        try {
          const j = await res.json();
          if (j?.detail) detail = typeof j.detail === "string" ? j.detail : detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      const match = /filename="?([^"]+)"?/.exec(cd);
      const filename = match?.[1] || `desinfo_${windowKey}.pdf`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setOk(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur d’export");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="export-panel" aria-label="Export PDF">
      {!open ? (
        <button type="button" className="export-toggle" onClick={() => setOpen(true)}>
          Exporter en PDF
        </button>
      ) : (
        <form className="export-form" onSubmit={onSubmit}>
          <h2>Export PDF</h2>
          <p className="export-hint">
            Fenêtre <strong>{windowKey}</strong>. L’e-mail est obligatoire ; le
            fichier est watermarké (e-mail + date + URL).
          </p>
          <label className="export-field">
            <span>E-mail</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(ev) => setEmail(ev.target.value)}
              placeholder="vous@exemple.fr"
            />
          </label>
          {/* honeypot — hidden from humans */}
          <label
            className="export-hp"
            aria-hidden="true"
            style={{
              position: "absolute",
              left: "-10000px",
              top: "auto",
              width: "1px",
              height: "1px",
              overflow: "hidden",
            }}
          >
            <span>Website</span>
            <input
              type="text"
              tabIndex={-1}
              autoComplete="off"
              value={website}
              onChange={(ev) => setWebsite(ev.target.value)}
            />
          </label>
          <label className="export-consent">
            <input
              type="checkbox"
              checked={consent}
              onChange={(ev) => setConsent(ev.target.checked)}
              required
            />
            <span>
              J’accepte que mon e-mail apparaisse en filigrane sur le PDF et soit
              conservé par l’Observatoire pour un éventuel suivi éditorial.
            </span>
          </label>
          {error && <p className="error">{error}</p>}
          {ok && <p className="export-ok">Téléchargement lancé.</p>}
          <div className="export-actions">
            <button type="submit" disabled={busy}>
              {busy ? "Génération…" : "Télécharger le PDF"}
            </button>
            <button
              type="button"
              className="export-cancel"
              onClick={() => {
                setOpen(false);
                setError(null);
                setOk(false);
              }}
            >
              Annuler
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
