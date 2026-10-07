import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from morningpaper.collect import CollectionError, collect_repository
from morningpaper.core import fingerprint
from morningpaper.providers import ProviderError, generate_json, provider_settings
from morningpaper.source_cache import with_source


class SourceAndProviderTests(unittest.TestCase):
    def test_only_confirmed_public_repo_enters_shared_collection(self):
        class Client:
            def api(self,path):return {"private":True,"archived":False}
        with self.assertRaises(CollectionError):collect_repository(Client(),{"name":"team/private"},{},{},{})

    def test_package_source_is_verified_and_reused(self):
        text="---\nname: test\ndescription: A useful workflow.\n---\nRead evidence."
        candidate={"id":"one","fingerprint":"version","source_fingerprint":fingerprint(text),"repository":"owner/repo","commit_sha":"a"*40,"path":"skills/test/SKILL.md"}
        with tempfile.TemporaryDirectory() as folder, patch("morningpaper.source_cache.urllib.request.urlopen",return_value=io.BytesIO(text.encode())) as request:
            first=with_source(candidate,Path(folder));second=with_source(candidate,Path(folder))
            self.assertEqual(first["source_text"],text);self.assertEqual(second["source_text"],text);self.assertEqual(request.call_count,1)

    def test_changed_source_is_not_used_as_verified_evidence(self):
        candidate={"id":"one","fingerprint":"version","source_fingerprint":"different","repository":"owner/repo","commit_sha":"a"*40,"path":"skills/test/SKILL.md"}
        with tempfile.TemporaryDirectory() as folder, patch("morningpaper.source_cache.urllib.request.urlopen",return_value=io.BytesIO(b"changed")), self.assertRaises(ProviderError):
            with_source(candidate,Path(folder))

    def test_json_api_contract_and_extra_field_validation(self):
        schema={"type":"object","additionalProperties":False,"required":["ready"],"properties":{"ready":{"type":"boolean"}}}
        response={"choices":[{"finish_reason":"stop","message":{"content":'{"ready":true}'}}]}
        with tempfile.TemporaryDirectory() as folder, patch("morningpaper.providers.urlopen",return_value=io.BytesIO(json.dumps(response).encode())) as send:
            result=generate_json("Return JSON",{"public":"sample"},schema,{"id":"deepseek"},Path(folder),secret="test-key")
            self.assertTrue(result["ready"])
            body=json.loads(send.call_args.args[0].data)
            self.assertEqual(body["model"],"deepseek-flash");self.assertEqual(body["response_format"],{"type":"json_object"})
            self.assertNotIn("tools",body)

    def test_credentials_in_endpoint_are_rejected(self):
        with self.assertRaises(ValueError):provider_settings({"id":"compatible","model":"m","base_url":"https://user:password@example.com"})


if __name__=="__main__":unittest.main()
