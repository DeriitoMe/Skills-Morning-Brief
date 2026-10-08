import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from morningpaper.core import read_json, write_json
from morningpaper.private_store import PrivateStore
from morningpaper.public_monitor import growth_rows, observe_repository, public_home
from morningpaper.shelf_daily import refresh_all


class PublicMonitorTests(unittest.TestCase):
    def test_growth_uses_real_sample_window(self):
        state={}
        observe_repository(state,"owner/repo",1000,"2026-10-06T03:00:00+00:00")
        observe_repository(state,"owner/repo",1200,"2026-10-06T08:00:00+00:00")
        row=growth_rows(state)[0]
        self.assertEqual(row["delta"],200);self.assertEqual(row["hours"],5);self.assertEqual(row["percent"],20)
        self.assertTrue(row["fast_growth"])

    def test_date_only_snapshot_cannot_become_invented_hourly_growth(self):
        state={"repositories":{"owner/repo":{"star_snapshots":{"2026-10-05":1000,"2026-10-06":2000}}}}
        self.assertEqual(growth_rows(state),[])

    def test_public_cards_never_include_private_matching_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            row={"id":"one","name":"public-skill","repository":"owner/repo","stars":5000,"summary":"useful",
                 "general_score":90,"matched_existing":["private-user-skill"],"score":99,"goals":"private-business","workspace_id":"private-id"}
            write_json(root/"data/public/catalog.json",{"items":[row],"repositories":[],"updated_at":"2026-10-06T00:00:00+00:00"})
            h=public_home(root)
            self.assertTrue(h["skills"])
            for key in ("matched_existing","score","goals","workspace_id"):self.assertNotIn(key,h["skills"][0])

    def test_public_update_works_without_any_personal_profile(self):
        from morningpaper.core import ROOT
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"config.toml").write_text((ROOT/"config.toml").read_text(encoding="utf-8"),encoding="utf-8")
            store=PrivateStore(root/"private")
            with patch("morningpaper.tibo_watch.refresh_tibo",return_value={"status":"partial","new_count":0,"updated_count":0,"verified_count":0,"pending_count":0,"sources":[]}), patch("morningpaper.shelf_daily.collect",return_value=([],[],[],0)),patch("morningpaper.shelf_daily.evaluate_catalog") as neutral,patch("morningpaper.public_news.refresh_public_news",return_value={"items":[{"id":"public-news"}]}),patch("morningpaper.shelf_daily.generate_personal") as personal:
                result=refresh_all(root,store)
            neutral.assert_called_once();personal.assert_not_called()
            self.assertEqual(result["public_news"],1);self.assertEqual(result["workspaces"],[])

    def test_personal_background_work_is_opt_in(self):
        from morningpaper.core import ROOT
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"config.toml").write_text((ROOT/"config.toml").read_text(encoding="utf-8"),encoding="utf-8")
            store=PrivateStore(root/"private");store.create_workspace({"name":"optional","goals":"work"})
            with patch("morningpaper.tibo_watch.refresh_tibo",return_value={"status":"partial","new_count":0,"updated_count":0,"verified_count":0,"pending_count":0,"sources":[]}), patch("morningpaper.shelf_daily.collect",return_value=([],[],[],0)),patch("morningpaper.shelf_daily.evaluate_catalog"),patch("morningpaper.public_news.refresh_public_news",return_value={"items":[]}),patch("morningpaper.shelf_daily.generate_personal") as personal:
                result=refresh_all(root,store)
            personal.assert_not_called();self.assertEqual(result["workspaces"],[])
