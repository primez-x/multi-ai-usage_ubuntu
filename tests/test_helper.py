import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "bin" / "ai_usage_tracker_helper.py"


spec = importlib.util.spec_from_file_location("ai_usage_tracker_helper", HELPER_PATH)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class HelperTests(unittest.TestCase):
    def test_codex_payload_maps_all_usage_windows(self):
        payload = {
            "plan_type": "pro",
            "credits": {"has_credits": True, "balance": 42},
            "rate_limit": {
                "primary_window": {
                    "used_percent": 25.4,
                    "limit_window_seconds": 18_000,
                    "reset_at": 1_765_000_000,
                },
                "secondary_window": {
                    "used_percent": 88,
                    "limit_window_seconds": 604_800,
                    "reset_at": 1_765_100_000,
                },
            },
            "additional_rate_limits": [
                {
                    "limit_name": "GPT-5",
                    "rate_limit": {
                        "primary_window": {"used_percent": 10},
                        "secondary_window": {"used_percent": 20},
                    },
                }
            ],
        }

        snapshot = helper.map_codex_payload(payload)

        self.assertEqual(snapshot["source"], "codex-wham-api")
        self.assertEqual(snapshot["plan"], "pro")
        self.assertEqual(snapshot["credits"], 42)
        self.assertEqual(
            [window["label"] for window in snapshot["windows"]],
            ["Session", "Weekly", "GPT-5 (Session)", "GPT-5 (Weekly)"],
        )
        self.assertEqual(snapshot["windows"][0]["usedPercent"], 25.4)
        self.assertEqual(snapshot["windows"][0]["remainingPercent"], 74.6)

    def test_transient_error_preserves_previous_provider_snapshot(self):
        previous = {
            "status": "ok",
            "updatedAt": "2026-06-01T08:00:00Z",
            "source": "codex-wham-api",
            "plan": "pro",
            "credits": None,
            "windows": [{"label": "Session", "usedPercent": 40, "remainingPercent": 60}],
            "error": None,
        }
        error = helper.ProviderError(
            "Codex HTTP 429; retrying in 60s",
            status=429,
            transient=True,
            retry_after_seconds=60,
        )

        merged = helper.provider_error_state(
            provider_id="codex",
            provider=helper.PROVIDERS["codex"],
            previous=previous,
            error=error,
            now="2026-06-01T08:01:00Z",
        )

        self.assertEqual(merged["status"], "stale")
        self.assertEqual(merged["source"], previous["source"])
        self.assertEqual(merged["plan"], previous["plan"])
        self.assertEqual(merged["windows"], previous["windows"])
        self.assertEqual(merged["error"], "Codex HTTP 429; retrying in 60s")
        self.assertEqual(merged["retryAfterSeconds"], 60)

    def test_gsettings_array_parser_accepts_gvariant_output(self):
        self.assertEqual(
            helper.parse_gsettings_array("['codex', 'claude']"),
            ["codex", "claude"],
        )
        self.assertEqual(helper.parse_gsettings_array("@as []"), [])

    def test_glm_payload_maps_live_lite_plan_shape(self):
        # Mirrors a real GLM Coding Lite response: token limits carry only a
        # percentage + ms reset, the time limit carries counts, and order is
        # arbitrary (web first).
        payload = {
            "code": 200,
            "success": True,
            "data": {
                "level": "lite",
                "limits": [
                    {
                        "type": "TIME_LIMIT",
                        "unit": 5,
                        "number": 1,
                        "usage": 100,
                        "currentValue": 18,
                        "remaining": 82,
                        "percentage": 18,
                        "nextResetTime": 1_784_162_904_979,
                    },
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 3,
                        "number": 5,
                        "percentage": 72,
                        "nextResetTime": 1_781_592_186_437,
                    },
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 6,
                        "number": 1,
                        "percentage": 14,
                        "nextResetTime": 1_782_175_704_969,
                    },
                ],
            },
        }

        snapshot = helper.map_glm_payload(payload, "GLM Coding Lite")

        self.assertEqual(snapshot["source"], "zai-quota-api")
        self.assertEqual(snapshot["plan"], "GLM Coding Lite")
        self.assertEqual(
            [w["label"] for w in snapshot["windows"]],
            ["Session", "Weekly", "Web Searches"],
        )
        session, weekly, web = snapshot["windows"]
        self.assertEqual(session["usedPercent"], 72)
        self.assertEqual(session["remainingPercent"], 28)
        self.assertEqual(session["windowMinutes"], 300)
        self.assertTrue(session["resetsAt"].endswith("Z"))
        self.assertEqual(weekly["usedPercent"], 14)
        self.assertEqual(weekly["windowMinutes"], 10080)
        self.assertEqual(web["usedPercent"], 18)
        self.assertIn("18 / 100 used", web["detail"])

    def test_glm_payload_falls_back_to_level_when_no_plan(self):
        payload = {"data": {"level": "pro", "limits": [
            {"type": "TOKENS_LIMIT", "unit": 3, "percentage": 5},
        ]}}
        snapshot = helper.map_glm_payload(payload, None)
        self.assertEqual(snapshot["plan"], "Pro")

    def test_glm_token_window_derives_percent_from_counts(self):
        window = helper._glm_token_window(
            "Session",
            {"currentValue": 250_000_000, "usage": 1_000_000_000, "nextResetTime": 1_781_592_186_437},
            300,
        )
        self.assertEqual(window["usedPercent"], 25)
        self.assertIn("250,000,000 / 1,000,000,000 tokens used", window["detail"])

    def test_iso_from_unix_ms_handles_ms_and_bad_input(self):
        self.assertEqual(helper.iso_from_unix_ms(1_781_592_186_437)[:4], "2026")
        self.assertIsNone(helper.iso_from_unix_ms(None))
        self.assertIsNone(helper.iso_from_unix_ms("not-a-number"))

    def test_zai_token_only_used_when_base_url_is_zai(self):
        zai_env = {
            "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "abc.def",
        }
        self.assertEqual(helper._zai_token_from_env_map(zai_env), "abc.def")
        # A non-z.ai base URL must NOT leak an unrelated Anthropic token.
        other_env = {
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_AUTH_TOKEN": "secret",
        }
        self.assertIsNone(helper._zai_token_from_env_map(other_env))

    def test_is_zai_host_rejects_substring_lookalikes(self):
        # Real z.ai hosts.
        for url in (
            "https://api.z.ai/api/anthropic",
            "https://z.ai",
            "https://open.z.ai/api/paas/v4",
            "http://API.Z.AI/x",  # case-insensitive
        ):
            self.assertTrue(helper._is_zai_host(url), url)
        # Look-alikes / injection that a naive substring check would accept.
        for url in (
            "https://buzz.ai/v1",
            "https://xyz.ai/v1",
            "https://my-z.ai-mirror.net/v1",
            "https://z.ai.evil.com/v1",
            "https://api.anthropic.com/?ref=z.ai",
            "https://api.anthropic.com",
            "",
        ):
            self.assertFalse(helper._is_zai_host(url), url)

    def test_zai_token_not_leaked_to_lookalike_host(self):
        env = {
            "ANTHROPIC_BASE_URL": "https://z.ai.evil.com/api",
            "ANTHROPIC_AUTH_TOKEN": "real-anthropic-key",
        }
        self.assertIsNone(helper._zai_token_from_env_map(env))

    def test_parse_shell_env_file_reads_export_and_quotes(self, ):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
            fh.write("# comment\n")
            fh.write('export ANTHROPIC_BASE_URL="https://api.z.ai/api/anthropic"\n')
            fh.write("ANTHROPIC_AUTH_TOKEN='tok.en'\n")
            fh.write("BLANK=\n")
            path = fh.name
        try:
            env = helper._parse_shell_env_file(helper.pathlib.Path(path))
            self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")
            self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "tok.en")
            self.assertEqual(env["BLANK"], "")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
