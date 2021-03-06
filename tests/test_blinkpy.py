"""
Test full system.

Tests the system initialization and attributes of
the main Blink system.  Tests if we properly catch
any communication related errors at startup.
"""

import unittest
from unittest import mock
from blinkpy import api
from blinkpy.blinkpy import Blink
from blinkpy.sync_module import BlinkSyncModule
from blinkpy.login_handler import LoginHandler
from blinkpy.helpers.util import (
    http_req,
    create_session,
    BlinkException,
    BlinkURLHandler,
)
from blinkpy.helpers.constants import __version__
import tests.mock_responses as mresp

USERNAME = "foobar"
PASSWORD = "deadbeef"


@mock.patch("blinkpy.helpers.util.Session.send", side_effect=mresp.mocked_session_send)
class TestBlinkSetup(unittest.TestCase):
    """Test the Blink class in blinkpy."""

    def setUp(self):
        """Set up Blink module."""
        self.blink = Blink(username=USERNAME, password=PASSWORD)
        self.blink.sync["test"] = BlinkSyncModule(self.blink, "test", "1234", [])
        self.blink.urls = BlinkURLHandler("test")
        self.blink.session = create_session()

    def tearDown(self):
        """Clean up after test."""
        self.blink = None

    def test_initialization(self, mock_sess):
        """Verify we can initialize blink."""
        self.assertEqual(self.blink.version, __version__)
        self.assertEqual(self.blink.login_handler.data["username"], USERNAME)
        self.assertEqual(self.blink.login_handler.data["password"], PASSWORD)

    def test_bad_request(self, mock_sess):
        """Check that we raise an Exception with a bad request."""
        self.blink.session = create_session()
        explog = "WARNING:blinkpy.helpers.util:" "Response from server: 200 - foo"
        with self.assertRaises(BlinkException):
            http_req(self.blink, reqtype="bad")

        with self.assertLogs() as logrecord:
            http_req(self.blink, reqtype="post", is_retry=True)
        self.assertEqual(logrecord.output, [explog])

    def test_authentication(self, mock_sess):
        """Check that we can authenticate Blink up properly."""
        authtoken = self.blink.get_auth_token()["TOKEN_AUTH"]
        expected = mresp.LOGIN_RESPONSE["authtoken"]["authtoken"]
        self.assertEqual(authtoken, expected)

    def test_reauthorization_attempt(self, mock_sess):
        """Check that we can reauthorize after first unsuccessful attempt."""
        original_header = self.blink.get_auth_token()
        # pylint: disable=protected-access
        bad_header = {"Host": self.blink._host, "TOKEN_AUTH": "BADTOKEN"}
        # pylint: disable=protected-access
        self.blink._auth_header = bad_header
        self.assertEqual(self.blink.auth_header, bad_header)
        api.request_homescreen(self.blink)
        self.assertEqual(self.blink.auth_header, original_header)

    def test_multiple_networks(self, mock_sess):
        """Check that we handle multiple networks appropriately."""
        self.blink.networks = {
            "0000": {"onboarded": False, "name": "foo"},
            "5678": {"onboarded": True, "name": "bar"},
            "1234": {"onboarded": False, "name": "test"},
        }
        self.blink.get_ids()
        self.assertTrue("5678" in self.blink.network_ids)

    def test_multiple_onboarded_networks(self, mock_sess):
        """Check that we handle multiple networks appropriately."""
        self.blink.networks = {
            "0000": {"onboarded": False, "name": "foo"},
            "5678": {"onboarded": True, "name": "bar"},
            "1234": {"onboarded": True, "name": "test"},
        }
        self.blink.get_ids()
        self.assertTrue("0000" not in self.blink.network_ids)
        self.assertTrue("5678" in self.blink.network_ids)
        self.assertTrue("1234" in self.blink.network_ids)

    @mock.patch("blinkpy.blinkpy.time.time")
    def test_throttle(self, mock_time, mock_sess):
        """Check throttling functionality."""
        now = self.blink.refresh_rate + 1
        mock_time.return_value = now
        self.assertEqual(self.blink.last_refresh, None)
        self.assertEqual(self.blink.check_if_ok_to_update(), True)
        self.assertEqual(self.blink.last_refresh, None)
        with mock.patch(
            "blinkpy.sync_module.BlinkSyncModule.refresh", return_value=True
        ):
            self.blink.refresh()

        self.assertEqual(self.blink.last_refresh, now)
        self.assertEqual(self.blink.check_if_ok_to_update(), False)
        self.assertEqual(self.blink.last_refresh, now)

    def test_sync_case_insensitive_dict(self, mock_sess):
        """Check that we can access sync modules ignoring case."""
        self.assertEqual(self.blink.sync["test"].name, "test")
        self.assertEqual(self.blink.sync["TEST"].name, "test")

    @mock.patch("blinkpy.api.request_login")
    def test_unexpected_login(self, mock_login, mock_sess):
        """Check that we appropriately handle unexpected login info."""
        mock_login.return_value = None
        self.assertFalse(self.blink.get_auth_token())

    @mock.patch("blinkpy.api.request_homescreen")
    def test_get_cameras(self, mock_home, mock_sess):
        """Check retrieval of camera information."""
        mock_home.return_value = {
            "cameras": [
                {"name": "foo", "network_id": 1234, "id": 5678},
                {"name": "bar", "network_id": 1234, "id": 5679},
                {"name": "test", "network_id": 4321, "id": 0000},
            ]
        }
        result = self.blink.get_cameras()
        self.assertEqual(
            result,
            {
                "1234": [{"name": "foo", "id": 5678}, {"name": "bar", "id": 5679}],
                "4321": [{"name": "test", "id": 0000}],
            },
        )

    @mock.patch("blinkpy.api.request_homescreen")
    def test_get_cameras_failure(self, mock_home, mock_sess):
        """Check that on failure we initialize empty info and move on."""
        mock_home.return_value = {}
        result = self.blink.get_cameras()
        self.assertEqual(result, {})

    @mock.patch.object(LoginHandler, "send_auth_key")
    @mock.patch.object(Blink, "setup_post_verify")
    def test_startup_prompt(self, mock_send_key, mock_verify, mock_sess):
        """Test startup logic with command-line prompt."""
        mock_send_key.return_value = True
        mock_verify.return_value = True
        self.blink.no_prompt = False
        self.blink.key_required = True
        self.blink.available = True
        with mock.patch("builtins.input", return_value="1234"):
            self.blink.start()
        self.assertFalse(self.blink.key_required)

    def test_startup_no_prompt(self, mock_sess):
        """Test startup with no_prompt flag set."""
        self.blink.key_required = True
        self.blink.no_prompt = True
        self.blink.start()
        self.assertTrue(self.blink.key_required)
