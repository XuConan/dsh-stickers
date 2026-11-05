"""小红书接口层单测：用桩替换 requests，只验证协议与错误映射，不联网。"""

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from app.xhs import api as xhs_api
from app.xhs.api import XhsApi, XhsError, XhsNeedLogin

FIXTURE = pathlib.Path(__file__).with_name("fixtures") / "xhs_redmoji.json"


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload, ensure_ascii=False)
        self.content = self.text.encode("utf-8")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


def make_api(cookies=None, as_list=True):
    """cookies 传 {name: value}，落盘成 Playwright 风格的清单。"""
    data = [{"name": k, "value": v} for k, v in (cookies or {}).items()] if as_list else (cookies or {})
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False)
    tmp.close()
    return XhsApi(tmp.name)


class TestLoggedIn(unittest.TestCase):
    def test_no_cookie_file(self):
        api = XhsApi(pathlib.Path(tempfile.gettempdir()) / "no-such-xhs-cookie.json")
        self.assertFalse(api.logged_in())

    def test_with_web_session(self):
        api = make_api({"web_session": "abc", "a1": "x"})
        self.assertTrue(api.logged_in())

    def test_without_web_session(self):
        api = make_api({"a1": "x"})
        self.assertFalse(api.logged_in())

    def test_save_roundtrip(self):
        api = make_api({})
        api.save([{"name": "web_session", "value": "zzz"}])
        self.assertTrue(XhsApi(api.cookie_file).logged_in())


class TestErrors(unittest.TestCase):
    def test_need_login_maps_to_exception(self):
        api = make_api({"web_session": "abc"})
        body = {"code": -101, "success": False, "msg": "无登录信息，或登录信息为空"}
        with mock.patch.object(xhs_api.requests, "get", return_value=FakeResp(body)):
            with self.assertRaises(XhsNeedLogin) as ctx:
                api.my_smiles()
        self.assertIn("登录", str(ctx.exception))

    def test_404_becomes_error(self):
        api = make_api({"web_session": "abc"})
        with mock.patch.object(xhs_api.requests, "get", return_value=FakeResp({"code": 0}, status=404)):
            with self.assertRaises(XhsError) as ctx:
                api.my_smiles()
        self.assertIn("404", str(ctx.exception))

    def test_other_business_error(self):
        api = make_api({"web_session": "abc"})
        with mock.patch.object(xhs_api.requests, "get", return_value=FakeResp({"code": 500, "msg": "boom"})):
            with self.assertRaises(XhsError) as ctx:
                api.my_smiles()
        self.assertIn("boom", str(ctx.exception))


class TestSmilesPayload(unittest.TestCase):
    def test_reads_data_smiles(self):
        api = make_api({"web_session": "abc"})
        body = {"code": 0, "success": True, "data": {"smiles": [
            {"fileId": "a1", "fileName": "https://a/1.webp", "width": 240, "height": 240},
        ]}}
        with mock.patch.object(xhs_api.requests, "get", return_value=FakeResp(body)):
            out = api.my_smiles()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fileId"], "a1")

    def test_tolerates_missing_data(self):
        api = make_api({"web_session": "abc"})
        with mock.patch.object(xhs_api.requests, "get", return_value=FakeResp({"code": 0})):
            self.assertEqual(api.my_smiles(), [])


class TestRedmojiPayload(unittest.TestCase):
    def test_flattens_tabs(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        api = make_api({})
        with mock.patch.object(xhs_api.requests, "get", return_value=FakeResp(raw)):
            emojis = api.redmoji()
        self.assertEqual(len(emojis), 166)
        self.assertIn("image", emojis[0])
        self.assertIn("image_name", emojis[0])

    def test_no_login_needed(self):
        """免登录接口不该因为没 cookie 而抛 XhsNeedLogin。"""
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        api = make_api({})
        with mock.patch.object(xhs_api.requests, "get", return_value=FakeResp(raw)):
            self.assertTrue(api.redmoji())


if __name__ == "__main__":
    unittest.main()
