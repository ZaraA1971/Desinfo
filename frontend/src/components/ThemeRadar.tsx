"use client";

import type { RadarAxis, RadarProfile } from "@/lib/api";

type Props = {
  name: string;
  radar: RadarProfile;
};

function polar(cx: number, cy: number, r: number, angleRad: number) {
  return {
    x: cx + r * Math.sin(angleRad),
    y: cy - r * Math.cos(angleRad),
  };
}

function labelAnchor(angleRad: number): "start" | "middle" | "end" {
  const deg = ((angleRad * 180) / Math.PI + 360) % 360;
  if (deg > 55 && deg < 125) return "start";
  if (deg > 235 && deg < 305) return "end";
  return "middle";
}

/** Branch length ∝ CN count within this media (max theme = outer ring). */
function axisWeight(cn: number, maxCn: number): number {
  if (maxCn <= 0 || cn <= 0) return 0;
  return cn / maxCn;
}

export function ThemeRadar({ name, radar }: Props) {
  const axes = radar.axes || [];
  const n = axes.length;
  const width = 420;
  const height = 360;
  const cx = width / 2;
  const cy = height / 2;
  const maxR = 112;
  const labelR = maxR + 36;
  const levels = [0.25, 0.5, 0.75, 1];
  const maxCn = Math.max(0, ...axes.map((a) => a.cn_count));

  if (n < 3) {
    return (
      <p className="radar-empty">
        Profil thématique insuffisant pour {name}.
      </p>
    );
  }

  const ringPaths = levels.map((lvl) => {
    const pts = Array.from({ length: n }, (_, i) => {
      const a = (2 * Math.PI * i) / n;
      return polar(cx, cy, maxR * lvl, a);
    });
    return (
      pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ") +
      " Z"
    );
  });

  const spokeLines = Array.from({ length: n }, (_, i) => {
    const a = (2 * Math.PI * i) / n;
    const p = polar(cx, cy, maxR, a);
    return { x2: p.x, y2: p.y };
  });

  const valuePts = axes.map((ax, i) => {
    const a = (2 * Math.PI * i) / n;
    // Floor at 25% radius for zero; outer = theme with most CN for this media
    const w = axisWeight(ax.cn_count, maxCn);
    const r = maxR * (0.25 + 0.75 * w);
    return polar(cx, cy, r, a);
  });
  const poly =
    valuePts
      .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
      .join(" ") + " Z";

  const labels = axes.map((ax, i) => {
    const a = (2 * Math.PI * i) / n;
    const p = polar(cx, cy, labelR, a);
    return { ...ax, ...p, anchor: labelAnchor(a) };
  });

  return (
    <div className="radar-panel">
      <div className="radar-centiles" aria-label={`CN par thème — ${name}`}>
        <span className="radar-centiles-name">{name}</span>
        {axes.map((ax: RadarAxis) => (
          <span key={ax.theme} className="radar-centile">
            <span className="radar-centile-label">{ax.label}</span>
            <span className="radar-centile-val">{ax.cn_count}</span>
          </span>
        ))}
      </div>
      <div className="radar-chart-wrap">
        <svg
          className="radar-svg"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`Radar thématique de ${name}. Longueur des branches proportionnelle au nombre de CN.`}
        >
          {ringPaths.map((d, i) => (
            <path key={i} d={d} className="radar-ring" />
          ))}
          {spokeLines.map((s, i) => (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={s.x2}
              y2={s.y2}
              className="radar-spoke"
            />
          ))}
          <path d={poly} className="radar-poly" />
          {valuePts.map((p, i) => (
            <circle key={i} cx={p.x} cy={p.y} r={3.5} className="radar-node" />
          ))}
          {labels.map((lb) => (
            <text
              key={lb.theme}
              x={lb.x}
              y={lb.y}
              className="radar-label"
              textAnchor={lb.anchor}
              dominantBaseline="middle"
            >
              {lb.label}
            </text>
          ))}
        </svg>
        <p className="radar-caption">
          Longueur ∝ nombre de CN du média sur le thème (le max atteint le bord ;
          0 reste à 25&nbsp;% du rayon)
          {radar.coverage != null
            ? ` · couverture classée ${(radar.coverage * 100).toFixed(0)} %`
            : ""}
        </p>
      </div>
    </div>
  );
}
