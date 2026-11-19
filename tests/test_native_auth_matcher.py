"""Synthetic-only tests for local native Authorization candidate matching."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import native_auth_matcher as matcher  # noqa: E402


class NativeAuthMatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.storage = self.root / "storage.json"
        self.credentials = self.root / "proxy-creds.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_storage(self, encrypted="fixture-ciphertext"):
        self.storage.write_text(
            json.dumps({matcher.STORAGE_AUTH_KEY: encrypted, "unrelated": "UNRELATED_SENTINEL"}),
            encoding="utf-8",
        )

    def write_credentials(self, value):
        self.credentials.write_text(json.dumps(value), encoding="utf-8")

    def load(self, decrypted_auth, proxy, *, now=100):
        self.write_storage()
        self.write_credentials(proxy)
        decrypt = mock.Mock(return_value=decrypted_auth)
        inventory = matcher.load_candidate_inventory(
            self.storage,
            self.credentials,
            decrypt_value=decrypt,
            now=now,
        )
        return inventory, decrypt

    @staticmethod
    def _jwt(payload):
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return "synthetic-header." + encoded + ".synthetic-signature"

    @staticmethod
    def _native_digest(header_value):
        prefix = matcher.CLOUD_IDE_JWT_PREFIX
        if header_value.startswith(prefix):
            token = header_value[len(prefix):]
            prefix_kind = "cloud_ide_jwt"
        else:
            token = header_value
            prefix_kind = "none"
        return hashlib.sha256(token.encode("utf-8", "strict")).hexdigest(), prefix_kind

    def test_storage_token_and_proxy_token_jwt_alias_match_without_disclosure(self):
        secret = "SYNTHETIC_TOKEN_CASE_Sensitive_123"
        inventory, decrypt = self.load(
            json.dumps({
                "token": secret,
                "refreshToken": "SYNTHETIC_REFRESH_DO_NOT_READ",
                "userId": "SYNTHETIC_USER_DO_NOT_READ",
                "privateKey": "SYNTHETIC_PRIVATE_KEY_DO_NOT_READ",
            }),
            {"auth": {
                "token": secret,
                "jwt": secret,
                "refreshToken": "SYNTHETIC_PROXY_REFRESH_DO_NOT_READ",
                "device": {"privateKey": "SYNTHETIC_PROXY_KEY_DO_NOT_READ"},
            }},
        )

        result = inventory.match_authorization_value("Cloud-IDE-JWT " + secret)
        self.assertEqual(
            result.matched_sources,
            ("trae.storage.token", "proxy.token", "proxy.jwt"),
        )
        self.assertTrue(result.same_value)
        self.assertTrue(result.cloud_ide_jwt_prefix)
        decrypt.assert_called_once_with("fixture-ciphertext")

        public_text = repr(inventory) + repr(result) + json.dumps(
            {"sources": inventory.source_statuses, "candidates": inventory.candidate_statuses},
            default=lambda item: item.__dict__,
        )
        for forbidden in (
            secret,
            "SYNTHETIC_REFRESH_DO_NOT_READ",
            "SYNTHETIC_USER_DO_NOT_READ",
            "SYNTHETIC_PRIVATE_KEY_DO_NOT_READ",
            "SYNTHETIC_PROXY_REFRESH_DO_NOT_READ",
            "SYNTHETIC_PROXY_KEY_DO_NOT_READ",
            "UNRELATED_SENTINEL",
        ):
            self.assertNotIn(forbidden, public_text)

    def test_distinct_jwt_candidate_does_not_match_token_alias(self):
        inventory, _ = self.load(
            json.dumps({"token": "SameCase"}),
            {"auth": {"token": "SameCase", "jwt": "samecase"}},
        )
        result = inventory.match_authorization_value("SameCase")
        self.assertEqual(result.matched_sources, ("trae.storage.token", "proxy.token"))
        self.assertTrue(result.same_value)
        self.assertFalse(result.cloud_ide_jwt_prefix)

    def test_only_exact_prefix_is_removed_and_token_is_not_transformed(self):
        inventory, _ = self.load(
            json.dumps({"token": "CaseToken"}),
            {"token": "CaseToken", "jwt": "CaseToken "},
        )

        prefixed = inventory.match_authorization_value("Cloud-IDE-JWT CaseToken")
        self.assertEqual(prefixed.matched_sources, ("trae.storage.token", "proxy.token"))
        self.assertTrue(prefixed.cloud_ide_jwt_prefix)
        self.assertFalse(inventory.match_authorization_value("cloud-ide-jwt CaseToken").same_value)
        self.assertFalse(inventory.match_authorization_value("Bearer CaseToken").same_value)
        self.assertEqual(
            inventory.match_authorization_value("CaseToken ").matched_sources,
            ("proxy.jwt",),
        )
        self.assertFalse(inventory.match_authorization_value("casetoken").same_value)

    def test_raw_and_digest_interfaces_agree_without_disclosing_digest(self):
        secret = "SYNTHETIC_Digest_Token_CaseSensitive"
        inventory, _ = self.load(
            json.dumps({"token": secret}),
            {"auth": {"token": secret, "jwt": "different-synthetic-jwt"}},
        )
        raw_result = inventory.match_authorization_value("Cloud-IDE-JWT " + secret)
        digest_hex, prefix_kind = self._native_digest("Cloud-IDE-JWT " + secret)
        digest_result = inventory.match_token_digest(
            digest_hex,
            prefix_kind=prefix_kind,
            header_name="authorization",
        )

        self.assertEqual(raw_result, digest_result)
        self.assertEqual(digest_result.matched_sources, ("trae.storage.token", "proxy.token"))
        self.assertTrue(digest_result.same_value)
        self.assertTrue(digest_result.cloud_ide_jwt_prefix)
        safe_text = repr(digest_result) + json.dumps(digest_result.__dict__)
        self.assertNotIn(secret, safe_text)
        self.assertNotIn(digest_hex, safe_text)

    def test_digest_contract_strips_exact_prefix_once(self):
        secret = "SYNTHETIC_OnePrefixOnly"
        inventory, _ = self.load(
            json.dumps({"token": secret}),
            {"auth": {"jwt": secret}},
        )

        single_hex, single_prefix = self._native_digest("Cloud-IDE-JWT " + secret)
        single = inventory.match_token_digest(
            single_hex, prefix_kind=single_prefix, header_name="authorization"
        )
        self.assertTrue(single.same_value)
        self.assertEqual(single.matched_sources, ("trae.storage.token", "proxy.jwt"))

        double_hex, double_prefix = self._native_digest(
            "Cloud-IDE-JWT Cloud-IDE-JWT " + secret
        )
        double = inventory.match_token_digest(
            double_hex, prefix_kind=double_prefix, header_name="authorization"
        )
        self.assertFalse(double.same_value)
        self.assertEqual(double.reason, "no_match")

    def test_digest_aliases_case_and_distinct_jwt_are_exact(self):
        inventory, _ = self.load(
            json.dumps({"token": "CaseToken"}),
            {"auth": {"token": "CaseToken", "jwt": "casetoken"}},
        )
        same_hex, _ = self._native_digest("CaseToken")
        different_case_hex, _ = self._native_digest("casetoken")
        self.assertEqual(
            inventory.match_token_digest(same_hex).matched_sources,
            ("trae.storage.token", "proxy.token"),
        )
        self.assertEqual(
            inventory.match_token_digest(different_case_hex).matched_sources,
            ("proxy.jwt",),
        )

    def test_digest_rejects_bad_format_header_and_prefix_enums(self):
        inventory, _ = self.load(
            json.dumps({"token": "SYNTHETIC_TOKEN"}),
            {"auth": {"jwt": "SYNTHETIC_JWT"}},
        )
        cases = (
            ("SYNTHETIC_DIGEST_MUST_NOT_ECHO", "none", "authorization", "invalid_digest"),
            ("A" * 64, "none", "authorization", "invalid_digest"),
            ("g" * 64, "none", "authorization", "invalid_digest"),
            ("0" * 64, "none", "Authorization", "invalid_header_name"),
            ("0" * 64, "CLOUD_IDE_JWT", "authorization", "invalid_prefix_kind"),
        )
        for digest_hex, prefix_kind, header_name, reason in cases:
            with self.subTest(reason=reason, prefix_kind=prefix_kind):
                result = inventory.match_token_digest(
                    digest_hex, prefix_kind=prefix_kind, header_name=header_name
                )
                self.assertFalse(result.same_value)
                self.assertEqual(result.reason, reason)
                self.assertNotIn(digest_hex, repr(result))

        empty_digest = hashlib.sha256(b"").hexdigest()
        empty = inventory.match_token_digest(empty_digest)
        self.assertEqual(empty.reason, "empty_token_digest")
        self.assertFalse(empty.same_value)

    def test_empty_non_string_and_prefix_only_values_fail_closed(self):
        inventory, _ = self.load(
            json.dumps({"token": None}),
            {"auth": {"token": "", "jwt": 42}},
        )
        statuses = {item.source: item for item in inventory.candidate_statuses}
        self.assertEqual(statuses["trae.storage.token"].reason, "wrong_type")
        self.assertEqual(statuses["proxy.token"].reason, "empty_value")
        self.assertEqual(statuses["proxy.jwt"].reason, "wrong_type")

        for value in (None, 7, "", "Cloud-IDE-JWT "):
            result = inventory.match_authorization_value(value)
            self.assertFalse(result.same_value)
            self.assertEqual(result.matched_sources, ())
        prefix_only = inventory.match_authorization_value("Cloud-IDE-JWT ")
        self.assertTrue(prefix_only.cloud_ide_jwt_prefix)
        self.assertEqual(prefix_only.reason, "empty_header_value")

    def test_top_level_proxy_token_jwt_aliases_are_supported(self):
        inventory, _ = self.load(
            json.dumps({"token": "storage-token"}),
            {"token": "top-level-token", "jwt": "top-level-jwt"},
        )
        token_match = inventory.match_authorization_value("top-level-token")
        jwt_match = inventory.match_authorization_value("top-level-jwt")
        self.assertEqual(token_match.matched_sources, ("proxy.token",))
        self.assertEqual(jwt_match.matched_sources, ("proxy.jwt",))

    def test_duplicate_auth_object_uses_last_object_without_old_child_values(self):
        self.write_storage()
        self.credentials.write_text(
            '{"auth":{"token":"OLD_TOKEN"},"auth":{}}', encoding="utf-8"
        )
        inventory = matcher.load_candidate_inventory(
            self.storage,
            self.credentials,
            decrypt_value=lambda _: json.dumps({"token": "storage-token"}),
            now=100,
        )
        self.assertFalse(inventory.match_authorization_value("OLD_TOKEN").same_value)
        statuses = {item.source: item for item in inventory.candidate_statuses}
        self.assertEqual(statuses["proxy.token"].reason, "missing_field")

    def test_expiration_is_a_boolean_claim_only_and_unknown_for_non_jwt(self):
        expired = self._jwt({"exp": 99, "user_id": "SYNTHETIC_USER_CLAIM"})
        current = self._jwt({"exp": 100})
        unknown = "not-a-jwt"
        inventory, _ = self.load(
            json.dumps({"token": expired}),
            {"auth": {"token": current, "jwt": unknown}},
            now=100,
        )
        statuses = {item.source: item for item in inventory.candidate_statuses}
        self.assertIs(statuses["trae.storage.token"].expired, True)
        self.assertIs(statuses["proxy.token"].expired, True)
        self.assertIsNone(statuses["proxy.jwt"].expired)
        report = json.dumps(inventory.candidate_statuses, default=lambda item: item.__dict__)
        self.assertNotIn("SYNTHETIC_USER_CLAIM", report)
        self.assertNotIn(expired, report)

    def test_missing_files_and_invalid_json_have_fixed_reasons(self):
        inventory = matcher.load_candidate_inventory(
            self.root / "missing-storage.json",
            self.root / "missing-creds.json",
            decrypt_value=lambda _: self.fail("decrypt must not run for missing file"),
            now=100,
        )
        sources = {item.source: item for item in inventory.source_statuses}
        candidates = {item.source: item for item in inventory.candidate_statuses}
        self.assertEqual(sources["trae_storage"].reason, "missing_file")
        self.assertEqual(sources["proxy_credentials"].reason, "missing_file")
        self.assertFalse(candidates["trae.storage.token"].present)
        self.assertEqual(candidates["proxy.jwt"].reason, "missing_file")

        self.storage.write_text('{"broken":', encoding="utf-8")
        self.credentials.write_text('{"auth":', encoding="utf-8")
        bad = matcher.load_candidate_inventory(
            self.storage,
            self.credentials,
            decrypt_value=lambda _: self.fail("decrypt must not run for invalid JSON"),
            now=100,
        )
        self.assertEqual({item.source: item.reason for item in bad.source_statuses}, {
            "trae_storage": "invalid_json",
            "proxy_credentials": "invalid_json",
        })

    def test_wrong_root_types_and_auth_types_are_reported_safely(self):
        self.storage.write_text("[]", encoding="utf-8")
        self.credentials.write_text('{"auth":[]}', encoding="utf-8")
        inventory = matcher.load_candidate_inventory(
            self.storage,
            self.credentials,
            decrypt_value=lambda _: self.fail("decrypt must not run for wrong root"),
            now=100,
        )
        self.assertEqual({item.source: item.reason for item in inventory.source_statuses}, {
            "trae_storage": "invalid_root_type",
            "proxy_credentials": "auth_section_wrong_type",
        })

    def test_decrypt_exception_and_bad_decrypted_json_use_fixed_reasons(self):
        self.write_storage()
        self.write_credentials({"auth": {"token": "proxy-only"}})
        failing = matcher.load_candidate_inventory(
            self.storage,
            self.credentials,
            decrypt_value=lambda _: (_ for _ in ()).throw(RuntimeError("SYNTHETIC_SECRET_ERROR")),
            now=100,
        )
        self.assertEqual(
            next(item.reason for item in failing.candidate_statuses if item.source == "trae.storage.token"),
            "decrypt_failed",
        )
        self.assertNotIn("SYNTHETIC_SECRET_ERROR", repr(failing))

        malformed = matcher.load_candidate_inventory(
            self.storage,
            self.credentials,
            decrypt_value=lambda _: '{"token":',
            now=100,
        )
        self.assertEqual(
            next(item.reason for item in malformed.candidate_statuses if item.source == "trae.storage.token"),
            "decrypted_auth_invalid_json",
        )

    def test_selective_parser_skips_unselected_plaintext_strings(self):
        payload = (
            '{"token":"selected-token","refreshToken":"\\ud800",'
            '"privateKey":"SYNTHETIC_PRIVATE_KEY"}'
        )
        self.write_storage()
        self.write_credentials({"auth": {"token": "proxy-token"}})
        inventory = matcher.load_candidate_inventory(
            self.storage,
            self.credentials,
            decrypt_value=lambda _: payload,
            now=100,
        )
        self.assertTrue(inventory.match_authorization_value("selected-token").same_value)
        self.assertNotIn("SYNTHETIC_PRIVATE_KEY", repr(inventory))

    def test_cli_default_only_checks_existence_and_live_summary_never_dumps_values(self):
        self.write_storage()
        self.write_credentials({"auth": {"token": "SYNTHETIC_CLI_TOKEN"}})

        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(
            matcher, "load_candidate_inventory", side_effect=AssertionError("default CLI read secrets")
        ):
            exit_code = matcher.main([
                "--storage-path", str(self.storage),
                "--credentials-path", str(self.credentials),
            ])
        self.assertEqual(exit_code, 0)
        default_report = json.loads(output.getvalue())
        self.assertEqual(default_report["mode"], "safe_preview")
        self.assertFalse(default_report["live_read"])
        self.assertTrue(default_report["sources"]["trae_storage"]["exists"])
        self.assertNotIn("SYNTHETIC_CLI_TOKEN", output.getvalue())

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = matcher.main([
                "--live",
                "--storage-path", str(self.root / "missing-storage.json"),
                "--credentials-path", str(self.credentials),
            ])
        self.assertEqual(exit_code, 0)
        live_report = json.loads(output.getvalue())
        self.assertEqual(live_report["mode"], "live_read")
        self.assertTrue(live_report["candidates"]["proxy.token"]["present"])
        self.assertNotIn("SYNTHETIC_CLI_TOKEN", output.getvalue())

    def test_cli_argument_error_does_not_echo_untrusted_text(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = matcher.main(["--unknown-option", "SYNTHETIC_DO_NOT_ECHO"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(output.getvalue()), {
            "mode": "error", "reason": "invalid_arguments"
        })
        self.assertNotIn("SYNTHETIC_DO_NOT_ECHO", output.getvalue())


if __name__ == "__main__":
    unittest.main()
