"""Pure-function tests for line-oa. No network. Run via scripts/test-pure.sh."""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

from line_oa import config as cfgmod
from line_oa.client import CLIENT_VERSION, USER_AGENT, make_client, resolve_tag_names
from line_oa.commands._curate import (
    curate_chat,
    curate_event,
    curate_profile,
    derive_from,
)
from line_oa.commands.auth import _parse_curl
from line_oa.commands.list_chats import _is_waiting
from line_oa.commands.send import _make_send_id
from line_oa.commands.tag import _curate_tag, _ids_to_names, _mutation_response
from line_oa.errors import EXIT_NO_ACCOUNT, CliError

SAMPLE_BOT = "U26397124b8700690b7331d7a16436277"
SAMPLE_CHAT = "U585253bc9936faa1232995f87a2c7702"


CURL_SHORT_FLAG = f"""curl 'https://chat.line.biz/api/v1/bots/{SAMPLE_BOT}/chats/{SAMPLE_CHAT}' \\
  -b 'XSRF-TOKEN=fake-xsrf; chat-device-group=810; __Host-chat-ses=fake-host; ses=fake-ses' \\
  -H 'referer: https://chat.line.biz/{SAMPLE_BOT}/chat/{SAMPLE_CHAT}' \\
  -H 'user-agent: test'
"""

CURL_LONG_FLAG = f"""curl --cookie 'XSRF-TOKEN=xx; __Host-chat-ses=yy' \\
  -H 'referer: https://chat.line.biz/{SAMPLE_BOT}/chat/{SAMPLE_CHAT}' \\
  'https://chat.line.biz/api/v2/bots/{SAMPLE_BOT}/chats'
"""

CURL_HEADER_COOKIE = f"""curl 'https://chat.line.biz/api/v2/bots/{SAMPLE_BOT}/chats' \\
  -H 'cookie: XSRF-TOKEN=a; ses=b' \\
  -H 'referer: https://chat.line.biz/{SAMPLE_BOT}/chat/{SAMPLE_CHAT}'
"""

CURL_NO_REFERER = f"""curl 'https://chat.line.biz/api/v2/bots/{SAMPLE_BOT}/chats' \\
  -b 'XSRF-TOKEN=a; ses=b'"""

CURL_NO_COOKIES = """curl 'https://chat.line.biz/api/v2/bots/x' \\
  -H 'accept: application/json'
"""


class ParseCurlTests(unittest.TestCase):
    def test_short_flag_extracts_cookies(self):
        r = _parse_curl(CURL_SHORT_FLAG)
        self.assertEqual(r["cookies"]["XSRF-TOKEN"], "fake-xsrf")
        self.assertEqual(r["cookies"]["__Host-chat-ses"], "fake-host")
        self.assertEqual(r["cookies"]["chat-device-group"], "810")
        self.assertEqual(r["botId"], SAMPLE_BOT)

    def test_long_flag_extracts_cookies(self):
        r = _parse_curl(CURL_LONG_FLAG)
        self.assertEqual(r["cookies"]["XSRF-TOKEN"], "xx")
        self.assertEqual(r["cookies"]["__Host-chat-ses"], "yy")
        self.assertEqual(r["botId"], SAMPLE_BOT)

    def test_cookie_header_fallback(self):
        r = _parse_curl(CURL_HEADER_COOKIE)
        self.assertEqual(r["cookies"]["XSRF-TOKEN"], "a")
        self.assertEqual(r["cookies"]["ses"], "b")
        self.assertEqual(r["botId"], SAMPLE_BOT)

    def test_no_referer_yields_empty_botid(self):
        r = _parse_curl(CURL_NO_REFERER)
        self.assertEqual(r["botId"], "")
        self.assertEqual(r["cookies"]["XSRF-TOKEN"], "a")

    def test_no_cookies_raises(self):
        with self.assertRaises(CliError):
            _parse_curl(CURL_NO_COOKIES)


class SendIdTests(unittest.TestCase):
    PATTERN = re.compile(r"^U[a-f0-9]{32}_\d{13}_\d{8}$")

    def test_format(self):
        sid = _make_send_id(SAMPLE_CHAT)
        self.assertRegex(sid, self.PATTERN)
        self.assertTrue(sid.startswith(SAMPLE_CHAT + "_"))

    def test_uniqueness_across_many_calls(self):
        ids = {_make_send_id(SAMPLE_CHAT) for _ in range(1000)}
        # Same-ms collisions are possible. With 8 random digits per call,
        # P(any dupe across 1000 same-ms draws) is ~5e-3. Allow a couple.
        self.assertGreater(len(ids), 995)


class IsWaitingTests(unittest.TestCase):
    BOT = SAMPLE_BOT

    def test_customer_sent(self):
        chat = {"latestEvent": {"source": {"userId": SAMPLE_CHAT}}}
        self.assertTrue(_is_waiting(chat, self.BOT))

    def test_oa_sent_manual(self):
        chat = {"latestEvent": {"source": {"userId": self.BOT}}}
        self.assertFalse(_is_waiting(chat, self.BOT))

    def test_oa_sent_automated(self):
        chat = {"latestEvent": {
            "source": {"userId": self.BOT},
            "bizId": "__AUTO_RESPONSE",
        }}
        self.assertFalse(_is_waiting(chat, self.BOT))

    def test_no_latest_event(self):
        self.assertFalse(_is_waiting({}, self.BOT))

    def test_latest_event_no_source(self):
        self.assertFalse(_is_waiting({"latestEvent": {}}, self.BOT))

    def test_source_no_user(self):
        self.assertFalse(_is_waiting({"latestEvent": {"source": {}}}, self.BOT))


class DeriveFromTests(unittest.TestCase):
    BOT = SAMPLE_BOT
    CUSTOMER = SAMPLE_CHAT

    def test_customer(self):
        self.assertEqual(derive_from(self.CUSTOMER, None, self.BOT), "customer")

    def test_customer_with_biz_id_still_customer(self):
        # In real data customer events carry no bizId, but be lenient.
        self.assertEqual(
            derive_from(self.CUSTOMER, "__AUTO_RESPONSE", self.BOT), "customer"
        )

    def test_manual(self):
        self.assertEqual(
            derive_from(self.BOT, "fee7f450-6fec-11e9-b49a-fa163e670dc0", self.BOT),
            "manual",
        )

    def test_manual_no_biz_id(self):
        self.assertEqual(derive_from(self.BOT, None, self.BOT), "manual")

    def test_automated(self):
        self.assertEqual(
            derive_from(self.BOT, "__AUTO_RESPONSE", self.BOT), "automated"
        )

    def test_missing_source_treated_as_oa_side(self):
        # No source.userId → can't be customer; falls through to OA-side
        # discrimination via bizId.
        self.assertEqual(derive_from(None, "__AUTO_RESPONSE", self.BOT), "automated")
        self.assertEqual(derive_from(None, None, self.BOT), "manual")


class CurateEventTests(unittest.TestCase):
    BOT = SAMPLE_BOT
    CUSTOMER = SAMPLE_CHAT

    def test_message_sent_oa_manual(self):
        evt = {
            "type": "messageSent",
            "timestamp": 1700000000000,
            "source": {"userId": self.BOT},
            "bizId": "fee7f450-6fec-11e9-b49a-fa163e670dc0",
            "message": {"id": "613...", "type": "text", "text": "hi"},
        }
        self.assertEqual(curate_event(evt, self.BOT), {
            "id": "613...",
            "timestamp": 1700000000000,
            "from": "manual",
            "type": "text",
            "text": "hi",
            "contentHash": None,
        })

    def test_message_sent_automated(self):
        evt = {
            "type": "messageSent",
            "timestamp": 1700000000000,
            "source": {"userId": self.BOT},
            "bizId": "__AUTO_RESPONSE",
            "message": {"id": "1", "type": "text", "text": "auto"},
        }
        self.assertEqual(curate_event(evt, self.BOT)["from"], "automated")

    def test_message_received_customer(self):
        # LINE uses event type "message" (not "messageReceived") for inbound.
        evt = {
            "type": "message",
            "timestamp": 1700000000000,
            "source": {"userId": self.CUSTOMER},
            "message": {"id": "2", "type": "text", "text": "hello"},
        }
        self.assertEqual(curate_event(evt, self.BOT)["from"], "customer")

    def test_non_text_message_has_null_text(self):
        evt = {
            "type": "message",
            "timestamp": 1,
            "source": {"userId": self.CUSTOMER},
            "message": {"id": "x", "type": "sticker"},
        }
        result = curate_event(evt, self.BOT)
        self.assertEqual(result["type"], "sticker")
        self.assertIsNone(result["text"])

    def test_image_message_carries_content_hash(self):
        evt = {
            "type": "message",
            "timestamp": 1700000000000,
            "source": {"userId": self.CUSTOMER},
            "message": {
                "id": "613477392824664423",
                "type": "image",
                "contentHash": "2dc9fcn7HDxVhyAQexN0Mu==",
            },
        }
        result = curate_event(evt, self.BOT)
        self.assertEqual(result["type"], "image")
        self.assertEqual(result["contentHash"], "2dc9fcn7HDxVhyAQexN0Mu==")
        self.assertIsNone(result["text"])
        self.assertEqual(result["from"], "customer")

    def test_text_message_content_hash_is_null(self):
        evt = {
            "type": "messageSent",
            "timestamp": 1,
            "source": {"userId": self.BOT},
            "bizId": "manual-uuid",
            "message": {"id": "x", "type": "text", "text": "hi"},
        }
        self.assertIsNone(curate_event(evt, self.BOT)["contentHash"])

    def test_sticker_message_content_hash_is_null(self):
        # Stickers don't ride on chat-content.line.biz — leave contentHash null
        # even if LINE happens to put one on the message blob.
        evt = {
            "type": "message",
            "timestamp": 1,
            "source": {"userId": self.CUSTOMER},
            "message": {"id": "x", "type": "sticker", "contentHash": "ignored"},
        }
        self.assertIsNone(curate_event(evt, self.BOT)["contentHash"])

    def test_chat_read_event_dropped(self):
        evt = {
            "type": "chatRead",
            "timestamp": 1,
            "source": {"userId": self.CUSTOMER},
            "read": {"watermark": 1},
        }
        self.assertIsNone(curate_event(evt, self.BOT))


class CurateChatTests(unittest.TestCase):
    BOT = SAMPLE_BOT
    CUSTOMER = SAMPLE_CHAT

    def _chat(self, **overrides) -> dict:
        base = {
            "chatId": self.CUSTOMER,
            "read": False,
            "done": False,
            "followedUp": False,
            "lastReceivedAt": 1700000000000,
            "profile": {"name": "Customer", "iconHash": "noise"},
            "latestEvent": {
                "type": "messageReceived",
                "timestamp": 1700000001000,
                "source": {"userId": self.CUSTOMER},
                "message": {"type": "text", "text": "hello"},
            },
            # Fields that must be dropped by curation:
            "tagIds": ["should-be-dropped"],
            "muteAtPc": True,
            "lastReadAt": 1234,
        }
        base.update(overrides)
        return base

    def test_basic_projection(self):
        result = curate_chat(self._chat(), self.BOT)
        self.assertEqual(result, {
            "chatId": self.CUSTOMER,
            "name": "Customer",
            "unread": True,
            "done": False,
            "followedUp": False,
            "lastReceivedAt": 1700000000000,
            "latest": {
                "from": "customer",
                "type": "text",
                "text": "hello",
                "timestamp": 1700000001000,
            },
        })

    def test_drops_noise_fields(self):
        result = curate_chat(self._chat(), self.BOT)
        for noisy in ("tagIds", "muteAtPc", "lastReadAt", "iconHash"):
            self.assertNotIn(noisy, result)

    def test_unread_inverts_read(self):
        self.assertFalse(curate_chat(self._chat(read=True), self.BOT)["unread"])
        self.assertTrue(curate_chat(self._chat(read=False), self.BOT)["unread"])

    def test_no_latest_event(self):
        chat = self._chat()
        chat["latestEvent"] = {}
        # Empty dict is still truthy in Python, but our curate handles
        # missing message gracefully.
        result = curate_chat(chat, self.BOT)
        # latest is built but with all None inner fields when event is empty
        self.assertIn("latest", result)


class CurateProfileTests(unittest.TestCase):
    def test_projects_identity_slice(self):
        blob = {
            "chatType": "USER",
            "tagIds": ["dropped"],
            "profile": {
                "userId": "U...",
                "name": "Theme",
                "friend": True,
                "lastActivityExpiresAt": 1779000000000,
                "iconHash": "dropped",
            },
            "latestEvent": {"dropped": True},
            "lastReadAt": 999,
        }
        self.assertEqual(curate_profile(blob), {
            "name": "Theme",
            "friend": True,
            "chatType": "USER",
            "pushWindowExpiresAt": 1779000000000,
        })


class ResolveAccountTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = os.environ.pop("LINE_OA_ACCOUNT", None)

    def tearDown(self):
        os.environ.pop("LINE_OA_ACCOUNT", None)
        if self._env_backup is not None:
            os.environ["LINE_OA_ACCOUNT"] = self._env_backup

    def _cfg(self, current=None, accounts=None):
        return {
            "accounts": accounts or {},
            "currentAccount": current,
        }

    def test_flag_wins_over_env_and_config(self):
        os.environ["LINE_OA_ACCOUNT"] = "env-acct"
        cfg = self._cfg(
            current="cfg-acct",
            accounts={
                "flag-acct": {"botId": "Uflag"},
                "env-acct": {"botId": "Uenv"},
                "cfg-acct": {"botId": "Ucfg"},
            },
        )
        name, bot = cfgmod.resolve_account(cfg, "flag-acct")
        self.assertEqual(name, "flag-acct")
        self.assertEqual(bot, "Uflag")

    def test_env_beats_config(self):
        os.environ["LINE_OA_ACCOUNT"] = "env-acct"
        cfg = self._cfg(
            current="cfg-acct",
            accounts={
                "env-acct": {"botId": "Uenv"},
                "cfg-acct": {"botId": "Ucfg"},
            },
        )
        name, bot = cfgmod.resolve_account(cfg, None)
        self.assertEqual(name, "env-acct")
        self.assertEqual(bot, "Uenv")

    def test_fallback_to_current(self):
        cfg = self._cfg(current="cfg-acct", accounts={"cfg-acct": {"botId": "Ucfg"}})
        name, _ = cfgmod.resolve_account(cfg, None)
        self.assertEqual(name, "cfg-acct")

    def test_no_account_raises_exit5(self):
        cfg = self._cfg()
        with self.assertRaises(CliError) as ctx:
            cfgmod.resolve_account(cfg, None)
        self.assertEqual(ctx.exception.code, EXIT_NO_ACCOUNT)

    def test_unknown_account_raises_exit5(self):
        cfg = self._cfg(current="cfg-acct", accounts={"other": {"botId": "U"}})
        with self.assertRaises(CliError) as ctx:
            cfgmod.resolve_account(cfg, None)
        self.assertEqual(ctx.exception.code, EXIT_NO_ACCOUNT)


class ConfigRoundtripTests(unittest.TestCase):
    def test_load_empty_path_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            cfg = cfgmod.load(p)
            self.assertIn("cookies", cfg)
            self.assertIn("accounts", cfg)
            self.assertIsNone(cfg["currentAccount"])

    def test_save_load_roundtrip_preserves_data(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            cfg = {
                "baseUrl": "https://chat.line.biz",
                "timezoneOffset": 420,
                "cookies": {"a": "b", "c": "d"},
                "accounts": {"paypers": {"botId": "U" + "a" * 32}},
                "currentAccount": "paypers",
            }
            cfgmod.save(cfg, p)
            loaded = cfgmod.load(p)
            self.assertEqual(loaded, cfg)


class CurateChatWithTagsTests(unittest.TestCase):
    BOT = SAMPLE_BOT
    CUSTOMER = SAMPLE_CHAT

    def _chat(self, **overrides) -> dict:
        base = {
            "chatId": self.CUSTOMER,
            "read": False,
            "done": False,
            "followedUp": False,
            "lastReceivedAt": 1700000000000,
            "profile": {"name": "Customer"},
            "latestEvent": {},
            "tagIds": ["tagA", "tagB"],
        }
        base.update(overrides)
        return base

    def test_omits_tags_when_no_map(self):
        result = curate_chat(self._chat(), self.BOT)
        self.assertNotIn("tags", result)

    def test_includes_tags_resolved_to_names(self):
        result = curate_chat(
            self._chat(), self.BOT,
            tag_id_to_name={"tagA": "vip", "tagB": "support"},
        )
        self.assertEqual(result["tags"], ["vip", "support"])

    def test_unknown_id_renders_as_raw_id(self):
        # Unresolved IDs must surface as the raw string, not silently drop.
        result = curate_chat(
            self._chat(), self.BOT,
            tag_id_to_name={"tagA": "vip"},
        )
        self.assertEqual(result["tags"], ["vip", "tagB"])

    def test_empty_tag_ids_yields_empty_list(self):
        result = curate_chat(
            self._chat(tagIds=[]), self.BOT,
            tag_id_to_name={"tagA": "vip"},
        )
        self.assertEqual(result["tags"], [])

    def test_missing_tag_ids_field_yields_empty_list(self):
        chat = self._chat()
        del chat["tagIds"]
        result = curate_chat(chat, self.BOT, tag_id_to_name={})
        self.assertEqual(result["tags"], [])


class ResolveTagNamesTests(unittest.TestCase):
    CATALOG = [
        {"tagId": "id-vip", "name": "vip"},
        {"tagId": "id-support", "name": "support"},
        {"tagId": "id-spaces", "name": "Accounting Firm"},
    ]

    def test_all_resolve(self):
        ids, missing = resolve_tag_names(self.CATALOG, ["vip", "support"])
        self.assertEqual(ids, ["id-vip", "id-support"])
        self.assertEqual(missing, [])

    def test_preserves_input_order(self):
        ids, _ = resolve_tag_names(self.CATALOG, ["support", "vip"])
        self.assertEqual(ids, ["id-support", "id-vip"])

    def test_partial_resolve(self):
        ids, missing = resolve_tag_names(self.CATALOG, ["vip", "unknown"])
        # Even though one fails, resolved ones still come back — caller
        # decides whether to abort. (tag.py's _resolve_tag_args aborts.)
        self.assertEqual(ids, ["id-vip"])
        self.assertEqual(missing, ["unknown"])

    def test_name_with_spaces(self):
        ids, missing = resolve_tag_names(self.CATALOG, ["Accounting Firm"])
        self.assertEqual(ids, ["id-spaces"])
        self.assertEqual(missing, [])

    def test_empty_input(self):
        ids, missing = resolve_tag_names(self.CATALOG, [])
        self.assertEqual(ids, [])
        self.assertEqual(missing, [])


class TagCurationTests(unittest.TestCase):
    def test_curate_tag_drops_metadata(self):
        raw = {
            "tagId": "id-1", "name": "vip",
            "count": 7, "createdAt": 1, "updatedAt": 2,
        }
        self.assertEqual(_curate_tag(raw), {"id": "id-1", "name": "vip"})

    def test_ids_to_names_unknown_falls_back_to_id(self):
        catalog = [{"tagId": "a", "name": "alpha"}]
        self.assertEqual(_ids_to_names(catalog, ["a", "b"]), ["alpha", "b"])


class MutationResponseTests(unittest.TestCase):
    CATALOG = [
        {"tagId": "id-vip", "name": "vip"},
        {"tagId": "id-support", "name": "support"},
        {"tagId": "id-urgent", "name": "urgent"},
    ]

    def test_add_diff(self):
        out = _mutation_response(
            "acct", "U1", before_ids=["id-vip"],
            after_ids=["id-vip", "id-support"], catalog=self.CATALOG,
        )
        self.assertEqual(out["before"], ["vip"])
        self.assertEqual(out["after"], ["vip", "support"])
        self.assertEqual(out["added"], ["support"])
        self.assertEqual(out["removed"], [])

    def test_remove_diff(self):
        out = _mutation_response(
            "acct", "U1", before_ids=["id-vip", "id-support"],
            after_ids=["id-vip"], catalog=self.CATALOG,
        )
        self.assertEqual(out["added"], [])
        self.assertEqual(out["removed"], ["support"])

    def test_clear_diff(self):
        out = _mutation_response(
            "acct", "U1", before_ids=["id-vip", "id-urgent"],
            after_ids=[], catalog=self.CATALOG,
        )
        self.assertEqual(out["after"], [])
        self.assertEqual(set(out["removed"]), {"vip", "urgent"})

    def test_noop_diff(self):
        out = _mutation_response(
            "acct", "U1", before_ids=["id-vip"],
            after_ids=["id-vip"], catalog=self.CATALOG,
        )
        self.assertEqual(out["added"], [])
        self.assertEqual(out["removed"], [])


class ClientHeadersTests(unittest.TestCase):
    """If LINE bumps x-oa-chat-client-version, these will catch us at the boundary."""

    def test_required_headers_present(self):
        cfg = {
            "baseUrl": "https://chat.line.biz",
            "cookies": {"XSRF-TOKEN": "xx", "ses": "yy"},
        }
        with make_client(cfg, SAMPLE_BOT) as client:
            headers = client.headers
            self.assertIn("XSRF-TOKEN=xx", headers["Cookie"])
            self.assertEqual(headers["X-XSRF-TOKEN"], "xx")
            self.assertEqual(headers["x-oa-chat-client-version"], CLIENT_VERSION)
            self.assertEqual(headers["User-Agent"], USER_AGENT)
            self.assertIn(SAMPLE_BOT, headers["Referer"])


if __name__ == "__main__":
    unittest.main()
