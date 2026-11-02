import { HomeClient } from "@/components/HomeClient";
import { loadHomeInitial } from "@/lib/server-api";
import { SITE_DESCRIPTION, SITE_NAME, absoluteUrl } from "@/lib/site";
import type { Metadata } from "next";

/**
 * Server-rendered home: ranking/meta are fetched on the server so crawlers
 * receive editorial HTML (no BAILOUT_TO_CLIENT_SIDE_RENDERING shell).
 */
export const revalidate = 3600;

export const metadata: Metadata = {
  title: SITE_NAME,
  description: SITE_DESCRIPTION,
};

type SearchParams = Promise<{ kind?: string; window?: string }>;

export default async function HomePage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const sp = await searchParams;
  const initial = await loadHomeInitial(sp);

  return (
    <>
      {/* Explicit trailing slash — Metadata API may normalize it away. */}
      <link rel="canonical" href={absoluteUrl("/")} />
      <HomeClient initial={initial} />
    </>
  );
}
