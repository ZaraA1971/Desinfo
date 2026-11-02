import type { MetadataRoute } from "next";
import {
  DISALLOW_PATH_PREFIXES,
  SITE_ORIGIN,
  absoluteUrl,
} from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [...DISALLOW_PATH_PREFIXES],
      },
    ],
    sitemap: absoluteUrl("/sitemap.xml"),
    host: SITE_ORIGIN,
  };
}
