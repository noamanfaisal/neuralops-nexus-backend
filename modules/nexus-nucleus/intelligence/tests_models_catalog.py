"""
The model catalog (owner, 2026-11-04): a file built into the image, a newer
copy downloaded only when it is newer, whole (sha256) and valid, and one API
the app asks. Run:  python manage.py test intelligence.tests_models_catalog
"""
import hashlib
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from chat.tests import MentionRightFixture
from intelligence import models_catalog as mc


def _catalog(version="2099-01-01.1", deepseek=("deepseek-flash",)):
    return {"schema": 1, "version": version, "generated_at": "x",
            "providers": {"deepseek": [{"id": i, "label": i} for i in deepseek]}}


def _raw(cat) -> bytes:
    return json.dumps(cat).encode()


class CatalogFileTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        mc._memo.update(at=0.0, data=None)
        self.addCleanup(mc._memo.update, at=0.0, data=None)

    def served(self, http_get=None, **settings):
        with override_settings(MODELS_CATALOG_DIR=self.dir.name, MODELS_CATALOG_URL="https://get.test/models.json", **settings):
            result = mc.refresh(http_get) if http_get else None
            return result, mc.current(use_memo=False)

    def hosting(self, raw: bytes, sha: str | None = None):
        sha = sha if sha is not None else hashlib.sha256(raw).hexdigest()
        return lambda url: (sha + "  models.json\n").encode() if url.endswith(".sha256") else raw

    def test_the_built_in_catalog_is_valid_and_offers_deepseeks_real_ids(self):
        cat = mc.bundled()
        ids = [m["id"] for m in cat["providers"]["deepseek"]]
        self.assertEqual(ids, ["deepseek-flash", "deepseek-v4-pro"])
        self.assertNotIn("deepseek-chat", ids)
        for provider in mc.PROVIDERS:
            self.assertTrue(cat["providers"][provider], provider)

    def test_with_nothing_downloaded_the_built_in_copy_is_served(self):
        _, cat = self.served()
        self.assertEqual(cat["version"], mc.bundled()["version"])

    def test_a_newer_whole_download_is_kept_and_served(self):
        raw = _raw(_catalog(deepseek=("deepseek-flash", "deepseek-v9")))
        result, cat = self.served(self.hosting(raw))
        self.assertTrue(result.startswith("updated"), result)
        self.assertEqual(cat["version"], "2099-01-01.1")
        self.assertEqual([m["id"] for m in cat["providers"]["deepseek"]], ["deepseek-flash", "deepseek-v9"])
        self.assertEqual((Path(self.dir.name) / "models.json").read_bytes(), raw)

    def test_a_checksum_that_does_not_match_is_refused_and_nothing_is_written(self):
        raw = _raw(_catalog())
        result, cat = self.served(self.hosting(raw, sha="0" * 64))
        self.assertIn("refused", result)
        self.assertFalse((Path(self.dir.name) / "models.json").exists())
        self.assertEqual(cat["version"], mc.bundled()["version"])

    def test_a_truncated_download_is_refused(self):
        raw = _raw(_catalog())
        cut = raw[: len(raw) // 2]
        result, _ = self.served(self.hosting(cut, sha=hashlib.sha256(raw).hexdigest()))
        self.assertIn("refused", result)

    def test_valid_json_of_the_wrong_shape_is_refused(self):
        for bad in ({"schema": 2, "version": "2099-01-01.1", "providers": {}},
                    {"schema": 1, "version": "tomorrow", "providers": {}},
                    {"schema": 1, "version": "2099-01-01.1", "providers": {"deepseek": [{"id": "bad id!"}]}}):
            result, _ = self.served(self.hosting(_raw(bad)))
            self.assertIn("refused", result, bad)

    def test_an_older_or_equal_hosted_copy_changes_nothing(self):
        raw = _raw(_catalog(version="2001-01-01.1"))
        result, cat = self.served(self.hosting(raw))
        self.assertTrue(result.startswith("unchanged"), result)
        self.assertFalse((Path(self.dir.name) / "models.json").exists())

    def test_offline_is_silent(self):
        def down(url):
            raise OSError("no route to host")
        result, cat = self.served(down)
        self.assertTrue(result.startswith("skipped"), result)
        self.assertEqual(cat["version"], mc.bundled()["version"])

    def test_a_cached_copy_edited_by_hand_is_ignored(self):
        raw = _raw(_catalog())
        self.served(self.hosting(raw))
        (Path(self.dir.name) / "models.json").write_bytes(raw.replace(b"deepseek-flash", b"deepseek-evil"))
        _, cat = self.served()
        self.assertEqual(cat["version"], mc.bundled()["version"])

    def test_a_newer_image_wins_over_an_older_download(self):
        raw = _raw(_catalog(version="2001-01-01.1"))
        Path(self.dir.name, "models.json").write_bytes(raw)
        Path(self.dir.name, "models.json.sha256").write_text(hashlib.sha256(raw).hexdigest())
        _, cat = self.served()
        self.assertEqual(cat["version"], mc.bundled()["version"])


class CatalogBuildTests(SimpleTestCase):
    def test_build_applies_hidden_recommended_labels_and_keeps_a_provider_without_a_key(self):
        previous = {"schema": 1, "version": "2026-11-04.1",
                    "providers": {"google": [{"id": "gemini-x", "label": "Gemini X"}]}}
        overrides = {"deepseek": {"hidden": ["deepseek-chat"], "recommended": ["deepseek-v4-pro", "deepseek-flash"],
                                  "labels": {"deepseek-flash": "Flash"}}}
        live = {"deepseek": [("deepseek-chat", "x"), ("deepseek-flash", "x"), ("deepseek-v4-pro", "y")]}
        cat = mc.build(previous=previous, overrides=overrides, live=live,
                       sizes=lambda p, i: (1_000_000, 8192) if p == "deepseek" else (None, None), today="2026-11-04")
        self.assertEqual(cat["version"], "2026-11-04.2")  # same day: the counter moves
        self.assertEqual([m["id"] for m in cat["providers"]["deepseek"]], ["deepseek-v4-pro", "deepseek-flash"])
        self.assertEqual(cat["providers"]["deepseek"][1]["label"], "Flash")
        self.assertEqual(cat["providers"]["deepseek"][0]["context_window"], 1_000_000)
        self.assertEqual([m["id"] for m in cat["providers"]["google"]], ["gemini-x"])  # no key: kept

    def test_provider_lists_drop_what_is_not_a_chat_model(self):
        body = {"data": [{"id": i} for i in ("gpt-5", "text-embedding-3-large", "gpt-4o-2024-08-06",
                                              "gpt-4o-realtime-preview", "dall-e-3", "gpt-5-mini")]}
        ids = [i for i, _ in mc.provider_ids("openai", "k", lambda url, headers: body)]
        self.assertEqual(ids, ["gpt-5-mini", "gpt-5"])

    def test_the_builder_keeps_only_ids_that_answer(self):
        answers = {"gpt-5": 200, "gpt-5-codex": 404}
        ok = [m for m in ("gpt-5", "gpt-5-codex")
              if mc.probe("openai", "k", m, lambda url, h, body: answers[body["model"]])]
        self.assertEqual(ok, ["gpt-5"])

    def test_dump_and_parse_round_trip_with_the_checksum(self):
        raw, sha = mc.dump(mc.validate(_catalog()))
        self.assertEqual(mc.parse(raw, sha)["version"], "2099-01-01.1")
        with self.assertRaises(mc.CatalogError):
            mc.parse(raw, "f" * 64)


class CatalogApiTests(MentionRightFixture):
    def test_the_app_gets_a_providers_ids_from_the_server(self):
        r = self.call("get", "/api/v1/model-catalog/?provider=deepseek", self.owner)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["version"], mc.bundled()["version"])
        self.assertEqual([m["id"] for m in body["models"]], ["deepseek-flash", "deepseek-v4-pro"])
        self.assertTrue(body["models"][0]["recommended"])
        self.assertEqual(body["models"][0]["context_window"], 1_000_000)

    def test_an_unknown_provider_is_an_empty_list(self):
        r = self.call("get", "/api/v1/model-catalog/?provider=ollama", self.owner)
        self.assertEqual(r.json()["models"], [])

    def test_someone_who_cannot_register_models_is_refused(self):
        r = self.call("get", "/api/v1/model-catalog/?provider=deepseek", self.vera)
        self.assertEqual(r.status_code, 403)
