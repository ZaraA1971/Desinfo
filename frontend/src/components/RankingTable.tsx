"use client";

import { useEffect, useMemo, useState } from "react";
import {
  MetricMode,
  RankingItem,
  formatCnPerPost,
  formatDelta,
  formatRatio,
  itemKey,
} from "@/lib/api";

type SortKey = "cn" | "posts" | "cn_per_post" | "post_per_cn";
type SortDir = "desc" | "asc";

type Props = {
  items: RankingItem[];
  metricMode: MetricMode | string;
  entityLabel?: string;
};

function numOrNeg(v: number | null | undefined): number {
  if (v == null || Number.isNaN(v)) return Number.NEGATIVE_INFINITY;
  return v;
}

function compareItems(a: RankingItem, b: RankingItem, key: SortKey, dir: SortDir): number {
  const mul = dir === "desc" ? -1 : 1;
  let va = 0;
  let vb = 0;
  switch (key) {
    case "cn":
      va = a.cn_count;
      vb = b.cn_count;
      break;
    case "posts":
      va = numOrNeg(a.post_count);
      vb = numOrNeg(b.post_count);
      break;
    case "cn_per_post":
      va = numOrNeg(a.rate_cn_per_post);
      vb = numOrNeg(b.rate_cn_per_post);
      break;
    case "post_per_cn":
      va = numOrNeg(a.ratio_post_per_cn);
      vb = numOrNeg(b.ratio_post_per_cn);
      break;
  }
  if (va !== vb) return (va < vb ? -1 : 1) * mul;
  return a.name.localeCompare(b.name, "fr");
}

function SortHeader({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
  className = "",
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  dir: SortDir;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = activeKey === sortKey;
  const marker = active ? (dir === "desc" ? " ↓" : " ↑") : "";
  return (
    <th className={`num sortable ${className}`} scope="col">
      <button
        type="button"
        className={`th-sort${active ? " is-active" : ""}`}
        onClick={() => onSort(sortKey)}
        aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
      >
        {label}
        {marker}
      </button>
    </th>
  );
}

export function RankingTable({
  items,
  metricMode,
  entityLabel = "Média",
}: Props) {
  const defaultKey: SortKey =
    metricMode === "post_cn" ? "cn_per_post" : "cn";
  const [sortKey, setSortKey] = useState<SortKey>(defaultKey);
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  useEffect(() => {
    setSortKey(defaultKey);
    setSortDir("desc");
  }, [defaultKey, items]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sorted = useMemo(() => {
    return [...items].sort((a, b) => compareItems(a, b, sortKey, sortDir));
  }, [items, sortKey, sortDir]);

  if (!items.length) {
    return (
      <p className="empty">
        Aucune donnée pour cette fenêtre. Lancez le bootstrap / ingest.
      </p>
    );
  }

  const showDelta = sortKey === defaultKey && sortDir === "desc";

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Rang</th>
            <th scope="col">{entityLabel}</th>
            <SortHeader
              label="CN"
              sortKey="cn"
              activeKey={sortKey}
              dir={sortDir}
              onSort={onSort}
              className="hide-sm"
            />
            <SortHeader
              label="Posts"
              sortKey="posts"
              activeKey={sortKey}
              dir={sortDir}
              onSort={onSort}
            />
            <SortHeader
              label="CN/Post"
              sortKey="cn_per_post"
              activeKey={sortKey}
              dir={sortDir}
              onSort={onSort}
              className="primary-metric"
            />
            <SortHeader
              label="Post/CN"
              sortKey="post_per_cn"
              activeKey={sortKey}
              dir={sortDir}
              onSort={onSort}
              className="hide-sm"
            />
          </tr>
        </thead>
        <tbody>
          {sorted.map((item, idx) => {
            const delta = item.delta_rank;
            const deltaClass =
              delta == null || delta === 0 ? "" : delta > 0 ? "up" : "down";
            return (
              <tr key={itemKey(item)}>
                <td className="rank">
                  {idx + 1}
                  {showDelta && delta != null && (
                    <span className={`delta ${deltaClass}`}>{formatDelta(delta)}</span>
                  )}
                </td>
                <td>
                  <span className="media-name">{item.name}</span>
                  {item.party && <span className="handle">{item.party}</span>}
                  {item.x_handle && (
                    <span className="handle">@{item.x_handle}</span>
                  )}
                </td>
                <td className="num hide-sm">{item.cn_count}</td>
                <td className="num">
                  {item.post_count == null ? "—" : item.post_count}
                </td>
                <td className="num">
                  {metricMode === "post_cn"
                    ? formatCnPerPost(item.rate_cn_per_post)
                    : item.cn_count}
                </td>
                <td className="num hide-sm">
                  {formatRatio(item.ratio_post_per_cn)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
