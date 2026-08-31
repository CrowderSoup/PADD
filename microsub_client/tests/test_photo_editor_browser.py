"""Opt-in Chromium smoke test for the touch photo-editing workflow.

Run with:
    PADD_BROWSER_TESTS=1 uv run pytest \
        microsub_client/tests/test_photo_editor_browser.py -s

The test creates the same Django session IndieAuth would create and mocks only
the external Micropub/media boundaries. It never adds a login bypass to the
application or contacts a real user service.
"""

import base64
import io
from importlib import import_module
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import requests
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from PIL import Image, ImageDraw

from microsub_client.models import Draft
from microsub_client.photo_id import photo_url_hash

from .conftest import SIMPLE_STORAGES


RUN_BROWSER_TESTS = os.environ.get("PADD_BROWSER_TESTS") == "1"
CHROMEDRIVER = shutil.which("chromedriver")


class WebDriver:
    """Tiny W3C WebDriver client; avoids adding Selenium just for one smoke test."""

    def __init__(self, base_url):
        self.base_url = base_url
        self.session_id = None

    def request(self, method, path, payload=None):
        response = requests.request(
            method,
            self.base_url + path,
            json=payload,
            timeout=15,
        )
        if not response.ok:
            raise AssertionError(
                f"WebDriver HTTP {response.status_code} for {path}: {response.text}"
            )
        body = response.json()
        value = body.get("value")
        if isinstance(value, dict) and value.get("error"):
            raise AssertionError(f"WebDriver error: {value}")
        return value

    def start(self):
        value = self.request("POST", "/session", {
            "capabilities": {"alwaysMatch": {
                "browserName": "chrome",
                "goog:chromeOptions": {"args": [
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--hide-scrollbars",
                    "--window-size=412,915",
                ]},
            }}
        })
        self.session_id = value["sessionId"]

    def command(self, method, suffix, payload=None):
        return self.request(method, f"/session/{self.session_id}{suffix}", payload)

    def cdp(self, command, params=None):
        return self.command("POST", "/goog/cdp/execute", {
            "cmd": command,
            "params": params or {},
        })

    def emulate_pixel(self):
        # Chrome's headless window has a 500px minimum. Device metrics override
        # provides the exact CSS viewport a phone page actually sees.
        self.cdp("Emulation.setDeviceMetricsOverride", {
            "width": 412,
            "height": 915,
            "deviceScaleFactor": 2.625,
            "mobile": True,
            "screenWidth": 412,
            "screenHeight": 915,
        })
        self.cdp("Emulation.setTouchEmulationEnabled", {
            "enabled": True,
            "maxTouchPoints": 5,
        })

    def navigate(self, url):
        self.command("POST", "/url", {"url": url})

    def execute(self, script, args=None):
        return self.command("POST", "/execute/sync", {
            "script": script,
            "args": args or [],
        })

    def touch_drag(self, start, end):
        self.command("POST", "/actions", {"actions": [{
            "type": "pointer",
            "id": "finger",
            "parameters": {"pointerType": "touch"},
            "actions": [
                {"type": "pointerMove", "duration": 0, "origin": "viewport",
                 "x": round(start[0]), "y": round(start[1])},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": 100},
                {"type": "pointerMove", "duration": 450, "origin": "viewport",
                 "x": round(end[0]), "y": round(end[1])},
                {"type": "pointerUp", "button": 0},
            ],
        }]})
        self.command("DELETE", "/actions")

    def screenshot(self, destination):
        png = base64.b64decode(self.command("GET", "/screenshot"))
        Path(destination).write_bytes(png)

    def close(self):
        if self.session_id:
            try:
                self.command("DELETE", "")
            finally:
                self.session_id = None


def wait_until(driver, expression, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if driver.execute(f"return Boolean({expression});"):
            return
        time.sleep(0.05)
    raise AssertionError(f"Browser condition did not become true: {expression}")


def sample_photo_bytes():
    image = Image.new("RGB", (900, 1200), "#315b78")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 90, 830, 1110), outline="#f89a25", width=28)
    draw.ellipse((190, 260, 710, 780), fill="#5fa8a0")
    draw.rectangle((250, 830, 650, 1020), fill="#f1c86e")
    output = io.BytesIO()
    image.save(output, "JPEG", quality=90)
    return output.getvalue()


@override_settings(
    STORAGES=SIMPLE_STORAGES,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class PhotoEditorTouchBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        if not RUN_BROWSER_TESTS:
            raise unittest.SkipTest("set PADD_BROWSER_TESTS=1 to run Chromium smoke tests")
        if not CHROMEDRIVER:
            raise unittest.SkipTest("chromedriver is not installed")
        super().setUpClass()

    def setUp(self):
        self.user_url = "https://browser-test.example/"
        self.original_url = "https://media.example/original.jpg"
        self.edited_url = "https://media.example/edited.jpg"
        self.draft = Draft.objects.create(
            user_url=self.user_url,
            content="Touch crop browser test",
            photos=[self.original_url],
        )

        SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
        session = SessionStore()
        session.update({
            "access_token": "browser-test-token",
            "user_url": self.user_url,
            "user_name": "Browser Test",
            "microsub_endpoint": "https://microsub.example/",
            "micropub_endpoint": "https://micropub.example/",
            "media_endpoint_url": "https://media.example/upload",
        })
        session.save()
        self.session_key = session.session_key

        photo_response = Mock()
        photo_response.content = sample_photo_bytes()
        photo_response.headers = {"Content-Type": "image/jpeg"}
        photo_response.status_code = 200
        photo_response.raise_for_status.return_value = None

        self.patchers = [
            patch("microsub_client.views.micropub.query_config", return_value={
                "media-endpoint": "https://media.example/upload",
                "syndicate-to": [],
            }),
            patch("microsub_client.views.safe_request", return_value=photo_response),
            patch("microsub_client.views.micropub.upload_media", return_value=self.edited_url),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.driver_dir = tempfile.TemporaryDirectory(prefix="padd-chromedriver-")
        self.addCleanup(self.driver_dir.cleanup)
        self.driver_log = Path(self.driver_dir.name) / "chromedriver.log"
        self.driver_port = 9517
        self.driver_process = subprocess.Popen(
            [CHROMEDRIVER, f"--port={self.driver_port}",
             f"--log-path={self.driver_log}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self._stop_driver)
        self.webdriver = WebDriver(f"http://127.0.0.1:{self.driver_port}")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                requests.get(f"http://127.0.0.1:{self.driver_port}/status", timeout=0.2).raise_for_status()
                break
            except requests.RequestException:
                time.sleep(0.05)
        else:
            self.fail(f"chromedriver did not start; log: {self.driver_log.read_text()}")
        self.webdriver.start()
        self.webdriver.emulate_pixel()
        self.addCleanup(self.webdriver.close)

    def _stop_driver(self):
        if self.driver_process.poll() is None:
            self.driver_process.terminate()
            self.driver_process.wait(timeout=5)

    def test_touch_crop_resize_and_save(self):
        driver = self.webdriver
        driver.navigate(self.live_server_url + "/")
        driver.command("POST", "/cookie", {"cookie": {
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.session_key,
            "path": "/",
        }})
        edit_url = (
            f"{self.live_server_url}/drafts/{self.draft.pk}/photo/"
            f"{photo_url_hash(self.original_url)}/edit/"
        )
        driver.navigate(edit_url)
        wait_until(driver, "document.querySelector('#photo-editor-canvas') && document.querySelector('#photo-editor-canvas').width > 0")

        driver.execute("document.querySelector('[data-editor-tool=\"adjust\"]').click();")
        wait_until(driver, "document.querySelector('.photo-editor-controls').dataset.activeTool === 'adjust'")
        self.assertNotEqual(
            driver.execute("return getComputedStyle(document.querySelector('[data-tool-panel=\"adjust\"]')).display;"),
            "none",
        )
        driver.execute("document.querySelector('[data-editor-tool=\"crop\"]').click();")
        wait_until(driver, "document.querySelector('.photo-editor-controls').dataset.activeTool === 'crop'")
        driver.execute("document.querySelector('[data-ratio=\"1\"]').click();")
        wait_until(driver, "document.querySelector('#photo-editor-canvas').classList.contains('photo-editor-canvas--crop-active')")

        metrics = driver.execute("""
            const canvas = document.querySelector('#photo-editor-canvas');
            const rect = canvas.getBoundingClientRect();
            return {
              left: rect.left, top: rect.top, width: rect.width, height: rect.height,
              saveBottom: document.querySelector('#photo-editor-upload').getBoundingClientRect().bottom,
              viewportHeight: window.innerHeight,
              viewportWidth: window.innerWidth,
              saveText: document.querySelector('#photo-editor-upload').textContent.trim(),
              hint: document.querySelector('.photo-editor-crop-hint').textContent.trim()
            };
        """)
        self.assertEqual(metrics["saveText"], "Save Photo")
        self.assertEqual(metrics["viewportWidth"], 412)
        self.assertLessEqual(metrics["saveBottom"], metrics["viewportHeight"])
        self.assertIn("corner", metrics["hint"])
        self.assertGreaterEqual(metrics["height"], 300)

        before_path = Path("/tmp/padd-photo-editor-before.png")
        after_path = Path("/tmp/padd-photo-editor-after.png")
        driver.screenshot(before_path)

        # A square crop on this portrait image touches the left and right edges;
        # pull the top-left handle inward to exercise real touch resizing.
        start = (metrics["left"] + 3, metrics["top"] + (metrics["height"] - metrics["width"]) / 2 + 3)
        end = (start[0] + 70, start[1] + 70)
        driver.touch_drag(start, end)
        driver.screenshot(after_path)
        self.assertNotEqual(before_path.read_bytes(), after_path.read_bytes())

        driver.execute("document.querySelector('#photo-editor-upload').click();")
        wait_until(driver, "location.pathname === '/new/'", timeout=15)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.photos, [self.edited_url])
