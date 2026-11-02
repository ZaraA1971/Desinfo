/** Public origin for Desinfo SEO (canonical, sitemap, robots). */
export const SITE_ORIGIN = "https://desinfo.electronlibre.info";

export const SITE_NAME = "Observatoire de la désinformation";

export const SITE_DESCRIPTION =
  "Palmarès roulant des médias français selon les Community Notes de X (densité CN / Posts).";

export const PUBLIC_INDEXABLE_PATHS = ["/"] as const;

export const DISALLOW_PATH_PREFIXES = [
  "/api/",
  "/_next/",
  "/health",
] as const;

export function absoluteUrl(path = "/"): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (normalized === "/") return `${SITE_ORIGIN}/`;
  return `${SITE_ORIGIN}${normalized}`;
}
