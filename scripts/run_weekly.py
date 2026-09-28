#!/usr/bin/env python3
"""Weekly desinfo job: CN ingest → themes → X 7d harvest → cascade → score → emails CSV."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.db import init_db
from backend.ingest.pipeline import run_ingest
from backend.politicians.rank import score_all_politicians_windows
from backend.scoring.bootstrap import bootstrap_roster
from backend.scoring.rank import score_all_windows
from backend.themes.classify import classify_pending_notes
from backend.x_client.sync import (
    cascade_longer_windows,
    cascade_politician_windows,
    run_weekly_harvest,
)


def load_or_bootstrap(force: bool):
    from backend.media_config import load_media_roster

    roster = load_media_roster()
    if force or not roster.get("media"):
        return bootstrap_roster()
    return roster


def main() -> int:
    parser = argparse.ArgumentParser(description="desinfo weekly pipeline")
    parser.add_argument(
        "--cascade-only",
        action="store_true",
        help="Skip CN ingest, themes and X API; recompute cascade + score only",
    )
    parser.add_argument("--skip-download", action="store_true", help="CN ingest from existing TSV")
    parser.add_argument(
        "--full-ingest",
        action="store_true",
        help="Re-ingest latest dump + full re-attribute (exceptionnel)",
    )
    parser.add_argument("--bootstrap", action="store_true", help="Rebuild media_roster.yml")
    parser.add_argument("--skip-themes", action="store_true", help="Skip LLM theme classification")
    parser.add_argument(
        "--skip-x-sync",
        action="store_true",
        help="Skip X 7d harvest (cascade from existing daily buckets only)",
    )
    parser.add_argument(
        "--theme-limit",
        type=int,
        default=None,
        help="Max notes to classify this run (default DESINFO_THEME_MAX_PER_RUN)",
    )
    parser.add_argument("--skip-score", action="store_true")
    parser.add_argument(
        "--skip-gov",
        action="store_true",
        help="Skip X public-code harvest of government measures",
    )
    parser.add_argument("--skip-emails", action="store_true")
    parser.add_argument("--windows", nargs="*", default=None)
    parser.add_argument(
        "--notify-only",
        action="store_true",
        help="Send current Desinfo state to Vigie, then exit",
    )
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    from backend.vigie_notify import brief_emails, brief_gov, brief_harvest, brief_ingest, brief_themes, push_weekly

    if args.notify_only:
        out = push_weekly({"status": "ok"})
        print("vigie:", "ok" if out.get("ok") else out)
        return 0 if out.get("ok") else 1

    init_db()
    run: dict = {"status": "ok", "reason": ""}

    try:
        if not args.cascade_only:
            result = run_ingest(skip_download=args.skip_download, full=args.full_ingest)
            # Avoid dumping tens of thousands of note ids into journald.
            print(
                "ingest:",
                {k: v for k, v in result.items() if k != "touched_note_ids"},
            )
            run["ingest"] = brief_ingest(result)

            roster = load_or_bootstrap(args.bootstrap)
            print("roster_size:", len(roster.get("media") or []))

            if not args.skip_themes:
                # Seule la semaine classe. Le thème est gardé, puis repris
                # tel quel dans le 30 j, le 90 j et l’année.
                themes = classify_pending_notes(
                    limit=args.theme_limit,
                    window_key="7d",
                )
                print("themes:", themes)
                run["themes"] = brief_themes(themes)
            else:
                print("themes: skipped")
                run["themes"] = "skipped"

        if args.cascade_only or args.skip_x_sync or not settings.x_api_configured:
            if not settings.x_api_configured and not args.cascade_only and not args.skip_x_sync:
                logging.warning("X_BEARER_TOKEN manquant — moisson X ignorée, cascade seule")
            harvest = {
                "sync": None,
                "cascade": cascade_longer_windows(),
                "politicians_cascade": cascade_politician_windows(),
            }
        else:
            harvest = run_weekly_harvest()
        print("harvest:", harvest)
        run["harvest"] = brief_harvest(harvest)

        if not args.skip_score:
            paths = score_all_windows(args.windows)
            print("snapshots:", [str(p) for p in paths])
            politician_paths = score_all_politicians_windows(args.windows)
            print("politicians_snapshots:", [str(p) for p in politician_paths])
            run["snapshots"] = [p.stem for p in paths] + [p.stem for p in politician_paths]

            if not args.skip_emails and not args.cascade_only:
                from backend.export.emails_csv import write_emails_csv

                csv_res = write_emails_csv()
                print("emails_csv:", csv_res)
                run["emails"] = brief_emails(csv_res)

            if not args.skip_gov:
                from backend.gov.sync import sync_gov_measures

                gov_res = sync_gov_measures()
                print("gov:", gov_res)
                run["gov"] = brief_gov(gov_res)

        return 0
    except Exception as exc:
        run["status"] = "failed"
        run["reason"] = str(exc)[:400]
        logging.exception("weekly pipeline failed")
        return 1
    finally:
        out = push_weekly(run)
        print("vigie:", "ok" if out.get("ok") else out)


if __name__ == "__main__":
    raise SystemExit(main())
