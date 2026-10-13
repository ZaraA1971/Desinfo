"""État hebdo → enveloppe Vigie, même si tout va."""
from __future__ import annotations

import unittest
from unittest import mock

from backend.vigie_notify import brief_emails, brief_ingest, build_weekly_payload


class VigieNotifyTests(unittest.TestCase):
    def test_ok_payload_is_complete(self):
        payload = build_weekly_payload(
            {
                "status": "ok",
                "ingest": {
                    "status": "skipped",
                    "reason": "no new dump days",
                    "dump_date": "2026-09-06",
                    "touched_note_ids": ["secret-note"],
                },
                "themes": {"status": "ok", "classified": 4, "pending_left": 1},
                "harvest": {
                    "sync": {
                        "status": "ok",
                        "unique_handles": 40,
                        "api_calls": 2,
                        "skipped_handles": 38,
                        "errors": [],
                    },
                    "cascade": {"status": "ok"},
                },
                "emails": {"rows": 10, "unique": 8, "latest": "/secret/path.csv"},
                "gov": {"measure_count": 3, "account_count": 12},
                "picture": {
                    "windows_ready": ["7j", "30j"],
                    "politicians_windows_ready": ["7j"],
                    "roster_size": 24,
                    "politicians_roster_size": 12,
                    "next_x_sync_at": "2026-09-14T06:00:00+00:00",
                    "theme_pending": 1,
                    "top_media": ["Reuters", "AFP"],
                    "top_politicians": ["Dupont"],
                },
            }
        )
        self.assertEqual(payload["kind"], "watch")
        self.assertEqual(payload["title"], "Desinfo — sync hebdo à jour")
        body = payload["body"]
        self.assertIn("Ingest", body)
        self.assertIn("Thèmes", body)
        self.assertIn("Réseaux", body)
        self.assertIn("Fenêtres", body)
        self.assertIn("Prochaine moisson", body)
        self.assertIn("Reuters", body)
        self.assertNotIn("secret-note", body)
        self.assertNotIn("/secret/path.csv", body)
        self.assertEqual(payload["facts"]["status"], "ok")
        self.assertEqual(payload["facts"]["theme"], "sync")
        self.assertTrue(payload["fingerprint"].startswith("desinfo:weekly:"))

    def test_failure_is_alert(self):
        payload = build_weekly_payload(
            {"status": "failed", "reason": "moisson interrompue", "picture": {}}
        )
        self.assertEqual(payload["kind"], "alert")
        self.assertEqual(payload["title"], "Desinfo — sync hebdo en échec")
        self.assertIn("moisson interrompue", payload["body"])
        self.assertEqual(payload["facts"]["status"], "failed")

    def test_briefs_drop_pii_and_ids(self):
        ingest = brief_ingest(
            {"status": "ok", "notes_upserted": 3, "touched_note_ids": ["n1"]}
        )
        self.assertNotIn("touched_note_ids", ingest)
        emails = brief_emails({"rows": 2, "unique": 1, "latest": "/tmp/x.csv"})
        self.assertEqual(emails, {"rows": 2, "unique": 1})


class VigiePushTests(unittest.TestCase):
    def test_push_always_posts(self):
        fake = mock.Mock()
        fake.door_facts = lambda **kw: kw
        fake.post_ingress.return_value = {"ok": True}
        with mock.patch.dict("sys.modules", {"vigie_door": fake}):
            from backend import vigie_notify

            out = vigie_notify.push_weekly(
                {
                    "status": "ok",
                    "picture": {
                        "next_x_sync_at": "2026-09-14T06:00:00+00:00",
                        "windows_ready": ["7j"],
                    },
                }
            )
        self.assertTrue(out.get("ok"))
        kwargs = fake.post_ingress.call_args.kwargs
        self.assertEqual(kwargs["source"], "desinfo")
        self.assertEqual(kwargs["kind"], "watch")
        self.assertIn("à jour", kwargs["title"])
        self.assertTrue(kwargs["body"])


if __name__ == "__main__":
    unittest.main()
