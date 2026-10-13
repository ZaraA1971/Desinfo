"use client";

import { Fragment, useMemo, useState } from "react";
import { GovMeasure, GovSnapshot } from "@/lib/api";

type Props = {
  snap: GovSnapshot;
};

function formatDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("fr-FR", { dateStyle: "long" });
}

function MeasureAccounts({ measure }: { measure: GovMeasure }) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase().replace(/^@/, "");
    if (!needle) return measure.accounts;
    return measure.accounts.filter(
      (a) =>
        a.handle.toLowerCase().includes(needle) || a.user_id.includes(needle),
    );
  }, [measure.accounts, q]);

  return (
    <div className="gov-accounts">
      <label className="gov-search">
        <span className="sr-only">Filtrer les comptes</span>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filtrer un @…"
        />
      </label>
      <p className="gov-accounts-meta">
        {filtered.length} compte{filtered.length > 1 ? "s" : ""}
        {q.trim() ? ` sur ${measure.account_count}` : ""}
      </p>
      <ul className="gov-handle-list">
        {filtered.map((a) => (
          <li key={`${a.user_id}-${a.handle}`}>
            <a
              href={`https://x.com/${a.handle}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              @{a.handle}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function GovMeasures({ snap }: Props) {
  const [openId, setOpenId] = useState<string | null>(null);

  if (!snap.measures?.length) {
    return (
      <p className="empty">
        Aucune mesure d’État n’a encore été lue dans le code public de X.
      </p>
    );
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Pays</th>
            <th scope="col">Mesure</th>
            <th scope="col" className="hide-sm">
              Autorité
            </th>
            <th scope="col">Effet</th>
            <th scope="col" className="num">
              Comptes
            </th>
          </tr>
        </thead>
        <tbody>
          {snap.measures.map((m) => {
            const isOpen = openId === m.id;
            return (
              <Fragment key={m.id}>
                <tr
                  className="row-clickable"
                  onClick={() => setOpenId(isOpen ? null : m.id)}
                  aria-expanded={isOpen}
                >
                  <td>
                    <span className="media-name">{m.country}</span>
                    {m.announced_at && (
                      <span className="handle">
                        Vu dans le code le {formatDay(m.announced_at)}
                      </span>
                    )}
                    {m.discovered && (
                      <span className="handle">Nouveau fichier, à préciser</span>
                    )}
                  </td>
                  <td>{m.title}</td>
                  <td className="hide-sm">{m.authority || "—"}</td>
                  <td>{m.effect}</td>
                  <td className="num">{m.account_count}</td>
                </tr>
                {isOpen && (
                  <tr className="radar-row">
                    <td colSpan={5}>
                      <div className="gov-detail">
                        {m.legal_basis && (
                          <p>
                            <strong>Base citée par X :</strong> {m.legal_basis}
                          </p>
                        )}
                        {m.source_url && (
                          <p>
                            Source :{" "}
                            <a
                              href={m.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              fichier dans le dépôt X
                            </a>
                          </p>
                        )}
                        <MeasureAccounts measure={m} />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
