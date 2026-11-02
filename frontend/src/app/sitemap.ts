import type { MetadataRoute } from "next";
import { PUBLIC_INDEXABLE_PATHS, absoluteUrl } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_INDEXABLE_PATHS.map((path) => ({
    url: absoluteUrl(path),
    changeFrequency: "daily",
    priority: 1,
  }));
}
