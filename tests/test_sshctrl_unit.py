#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from sshctrl_lib.alias import find_alias_exact, find_alias_fuzzy
from sshctrl_lib.collaborator import validate_linux_username
from sshctrl_lib.common import first_match_sshd_upsert_script, resolve_secret_password, validate_host
from sshctrl_lib.repair import build_vnc_auth_rescue_script, classify_ssh_debug_output


class ValidateHostTests(unittest.TestCase):
    def test_ipv4_ok(self):
        self.assertTrue(validate_host("198.44.177.126"))

    def test_ipv4_octet_out_of_range(self):
        self.assertFalse(validate_host("192.168.1.256"))

    def test_domain_ok(self):
        self.assertTrue(validate_host("connect.nmb2.seetacloud.com"))


class UsernameTests(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(validate_linux_username("alice_1"))

    def test_rejects_root_style_uppercase(self):
        self.assertFalse(validate_linux_username("Alice"))


class ClassifyTests(unittest.TestCase):
    def test_auth_layer(self):
        msg = classify_ssh_debug_output("Permission denied (publickey,password)")
        self.assertIn("认证层", msg)

    def test_sftp_layer(self):
        msg = classify_ssh_debug_output("subsystem request failed on channel 0")
        self.assertIn("SFTP", msg)

    def test_host_key(self):
        msg = classify_ssh_debug_output("REMOTE HOST IDENTIFICATION HAS CHANGED")
        self.assertIn("known_hosts", msg)


class SshdUpsertTests(unittest.TestCase):
    def test_first_match_only(self):
        script = first_match_sshd_upsert_script("PasswordAuthentication", "yes")
        self.assertIn("0,/^[[:space:]]*PasswordAuthentication", script)
        self.assertNotIn("s|^[[:space:]]*PasswordAuthentication.*|", script)


class PasswordEnvTests(unittest.TestCase):
    def test_dash_reads_env(self):
        with mock.patch.dict(os.environ, {"SSHCTRL_PASSWORD": "s3cret"}):
            self.assertEqual(resolve_secret_password("-"), "s3cret")

    def test_literal_password(self):
        self.assertEqual(resolve_secret_password("plain"), "plain")


class ConfigParseTests(unittest.TestCase):
    def test_exact_and_fuzzy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text(
                "Host blog-prod\n"
                "    HostName 198.44.177.126\n"
                "    User root\n"
                "    Port 22\n"
                "Host other\n"
                "    HostName 10.0.0.2\n"
                "    User deploy\n",
                encoding="utf-8",
            )
            exact = find_alias_exact("198.44.177.126", str(path))
            self.assertEqual(exact["alias"], "blog-prod")
            fuzzy = find_alias_fuzzy("blog", str(path))
            self.assertEqual(fuzzy[0]["alias"], "blog-prod")


class VncRescueTests(unittest.TestCase):
    def test_embeds_username_and_debian_service_fallback(self):
        script = build_vnc_auth_rescue_script("root")
        self.assertIn('TARGET_USER="root"', script)
        self.assertIn("systemctl restart sshd || systemctl restart ssh", script)


if __name__ == "__main__":
    unittest.main()
