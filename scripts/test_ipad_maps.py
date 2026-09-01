"""Regression tests for iPad map GPS + fullscreen.

Real iOS Safari cannot run on Windows. Apple's Simulator is Mac-only and
BrowserStack/Sauce are paid. This script is the free stand-in:

1. Static checks on the generated HTML (no extra packages).
2. Playwright Chromium with an iPad viewport + init-scripts that reproduce
   the two Safari failure modes the last trip app hit:

   - Geolocation: iPad Safari often ignores watchPosition() unless it is
     started from a tap. We mock the Geolocation API so the page's own
     locate button and auto-watch can be asserted.
   - Fullscreen: iPad Safari exposes requestFullscreen / webkitRequestFullscreen
     on HTMLElement but they are no-ops for anything but <video>. Checking
     that the method exists is not enough; the CSS fallback must still fire.

Install (free, one-time):

    pip install playwright
    python -m playwright install chromium

Run from the repo root:

    python scripts/test_ipad_maps.py
"""
from __future__ import annotations

import argparse
import http.server
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ITINERARY = ROOT / "trip-itinerary.html"
SETTINGS = ROOT / "settings.html"

# Takhlakh Lake — within 0.5 mi of CASCADE_GPS so auto-read can be asserted.
TAKHLAKH_GPS = {"latitude": 46.2782671, "longitude": -121.5963891}

IPAD_VIEWPORT = {"width": 834, "height": 1194}
IPAD_UA = (
    "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)
# The itinerary auto-opens a day tab when the local date matches a trip day.
# Tests must target the visible pane, not hard-code route_overview.
ACTIVE_WRAP = ".tab-pane.active .map-wrap"
CASCADE_GPS = {"latitude": 46.278, "longitude": -121.598}
NAMPA_GPS = {"latitude": 43.5405, "longitude": -116.563}


# ---------------------------------------------------------------------------
# Static checks (always run)
# ---------------------------------------------------------------------------

def _html() -> str:
    if not ITINERARY.is_file():
        raise SystemExit(f"missing {ITINERARY} — run python scripts/build_deliverables.py first")
    return ITINERARY.read_text(encoding="utf-8")


def test_static_fixes_present() -> None:
    html = _html()
    required = [
        ("user-gesture locate", "requestMyLocation("),
        ("iOS fullscreen capability check", "_fsNativeEnabled"),
        ("CSS fallback class", "is-fullscreen-fallback"),
        ("fallback above iPad nav", "z-index:20000"),
        ("GPS marker class", "wca-my-location"),
        ("locate button", "map-loc-btn"),
        ("safe-area viewport", "viewport-fit=cover"),
        ("high-accuracy timeout retry", "enableHighAccuracy: false"),
        ("Escape exits fallback", "is-fullscreen-fallback"),
        ("speakable catalog", "const SPEAKABLE_POIS"),
        ("listen button class", "speak-btn"),
        ("stop bar id", "wca-speak-bar"),
        ("settings helper", "WcaSpeakSettings"),
        ("approach hook", "_speakOnGps"),
        ("settings nav link", "settings.html"),
    ]
    missing = [name for name, needle in required if needle not in html]
    if missing:
        raise AssertionError("generated HTML is missing iPad fixes: " + ", ".join(missing))


def test_static_settings_page() -> None:
    if not SETTINGS.is_file():
        raise SystemExit(f"missing {SETTINGS} — run python scripts/build_deliverables.py first")
    html = SETTINGS.read_text(encoding="utf-8")
    required = [
        ("spoken notes heading", "Spoken notes"),
        ("enable checkbox", "speak-enabled"),
        ("scope radios", 'name="speak-scope"'),
        ("landmarks toggle", "speak-landmarks"),
        ("repeat toggle", "speak-repeat"),
        ("voice select", 'id="speak-voice"'),
        ("play sample", "speak-voice-play"),
        ("voice identity helper", "voiceKey"),
        ("settings helper", "WcaSpeakSettings"),
        ("sample text", "This is how notes will sound"),
    ]
    missing = [name for name, needle in required if needle not in html]
    if missing:
        raise AssertionError("settings.html is missing spoken-notes UI: " + ", ".join(missing))


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        pass


def _serve(directory: Path) -> tuple[socketserver.TCPServer, str]:
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(directory), **k)  # noqa: E731

    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            pass

    httpd = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address
    return httpd, f"http://{host}:{port}"


def _ios_fullscreen_noop_script() -> str:
    return """
    Object.defineProperty(document, 'fullscreenEnabled', {
      configurable: true, get: function() { return false; }
    });
    Object.defineProperty(document, 'webkitFullscreenEnabled', {
      configurable: true, get: function() { return false; }
    });
    Element.prototype.requestFullscreen = function() {
      return Promise.reject(new TypeError('Fullscreen not supported'));
    };
    Element.prototype.webkitRequestFullscreen = function() { return; };
    """


def _ios_fullscreen_silent_webkit_script() -> str:
    """Method exists, returns undefined, never enters fullscreen — classic iOS."""
    return """
    Object.defineProperty(document, 'fullscreenEnabled', {
      configurable: true, get: function() { return true; }
    });
    Element.prototype.requestFullscreen = function() { return; };
    Element.prototype.webkitRequestFullscreen = function() { return; };
    """


def _geo_script(lat: float, lon: float) -> str:
    return f"""
    (function() {{
      const pos = {{
        coords: {{
          latitude: {lat}, longitude: {lon}, accuracy: 20,
          altitude: null, altitudeAccuracy: null, heading: null, speed: null
        }},
        timestamp: Date.now()
      }};
      const geo = {{
        getCurrentPosition(success, error) {{
          setTimeout(function() {{ success(pos); }}, 20);
        }},
        watchPosition(success, error) {{
          success(pos);
          return 1;
        }},
        clearWatch: function() {{}}
      }};
      Object.defineProperty(navigator, 'geolocation', {{
        configurable: true, get: function() {{ return geo; }}
      }});
    }})();
    """


def _geo_timeout_then_low_accuracy_script(lat: float, lon: float) -> str:
    return f"""
    (function() {{
      const pos = {{
        coords: {{
          latitude: {lat}, longitude: {lon}, accuracy: 80,
          altitude: null, altitudeAccuracy: null, heading: null, speed: null
        }},
        timestamp: Date.now()
      }};
      const timeoutErr = {{ code: 3, message: 'Timeout', PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 }};
      const geo = {{
        getCurrentPosition(success, error, opts) {{
          const high = !opts || opts.enableHighAccuracy !== false;
          setTimeout(function() {{
            if (high) error(timeoutErr);
            else success(pos);
          }}, 20);
        }},
        watchPosition(success, error, opts) {{
          const high = !opts || opts.enableHighAccuracy !== false;
          setTimeout(function() {{
            if (high) error(timeoutErr);
            else success(pos);
          }}, 20);
          return 1;
        }},
        clearWatch: function() {{}}
      }};
      Object.defineProperty(navigator, 'geolocation', {{
        configurable: true, get: function() {{ return geo; }}
      }});
    }})();
    """


def _speech_mock_script() -> str:
    """On-device voices + a speak() log. Utterances stay open so Stop can fire."""
    return """
    (function() {
      window.__WCA_SPOKE = [];
      window.__WCA_VOICES = [
        {name:'Samantha', lang:'en-US', localService:true, default:true, voiceURI:'samantha'},
        {name:'Network Voice', lang:'en-GB', localService:false, default:false, voiceURI:'net-en'}
      ];
      function Utterance(text) {
        this.text = text;
        this.voice = null;
        this.rate = 1;
        this.volume = 1;
        this.onend = null;
        this.onerror = null;
      }
      const synth = {
        speaking: false,
        paused: false,
        pending: false,
        _current: null,
        getVoices: function() { return window.__WCA_VOICES; },
        speak: function(u) {
          window.__WCA_SPOKE.push(u && u.text);
          window.__WCA_LAST_UTTERANCE = {
            text: u && u.text,
            voiceURI: u && u.voice && u.voice.voiceURI,
            lang: u && (u.lang || (u.voice && u.voice.lang)),
            name: u && u.voice && u.voice.name
          };
          this.speaking = true;
          this._current = u;
        },
        cancel: function() {
          this.speaking = false;
          this._current = null;
          window.__WCA_SPOKE.push('__cancel__');
        },
        pause: function() {},
        resume: function() {},
        addEventListener: function() {},
        removeEventListener: function() {}
      };
      window.SpeechSynthesisUtterance = Utterance;
      Object.defineProperty(window, 'speechSynthesis', {
        configurable: true, get: function() { return synth; }
      });
    })();
    """


def _enable_speak_notes_script() -> str:
    return """
    try {
      localStorage.setItem('wca-speak-notes', '1');
      localStorage.setItem('wca-speak-notes-scope', 'all');
      localStorage.setItem('wca-speak-notes-landmarks', '1');
      localStorage.setItem('wca-speak-notes-repeat', '0');
    } catch (e) {}
    """


def _new_context(browser, init_scripts: list[str]):
    context = browser.new_context(
        viewport=IPAD_VIEWPORT,
        user_agent=IPAD_UA,
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2,
    )
    for script in init_scripts:
        context.add_init_script(script)
    page = context.new_page()
    page.set_default_timeout(30000)
    return context, page


def _new_page(browser, origin: str, init_scripts: list[str]):
    context, page = _new_context(browser, init_scripts)
    page.goto(origin + "/trip-itinerary.html", wait_until="domcontentloaded")
    page.wait_for_selector(".leaflet-container", timeout=30000)
    return context, page


def test_fullscreen_fallback_when_api_disabled(origin: str, browser) -> None:
    context, page = _new_page(browser, origin, [_ios_fullscreen_noop_script()])
    try:
        wrap = page.locator(ACTIVE_WRAP)
        btn = wrap.locator(".map-fs-btn")
        btn.click()
        page.wait_for_selector(ACTIVE_WRAP + ".is-fullscreen-fallback")
        box = wrap.bounding_box()
        assert box is not None, "fullscreen wrap has no box"
        assert box["height"] >= 700, f"fallback map too short: {box['height']}"
        z = page.evaluate(
            """() => {
              const el = document.querySelector('.tab-pane.active .map-wrap');
              return el ? getComputedStyle(el).zIndex : '';
            }"""
        )
        assert int(z) >= 20000, f"fallback z-index {z} loses to trip nav (10050)"
        nav_z = page.evaluate(
            """() => {
              const n = document.querySelector('[data-trip-nav]');
              return n ? getComputedStyle(n).zIndex : '0';
            }"""
        )
        assert int(z) > int(nav_z or 0), f"map z-index {z} not above nav {nav_z}"

        btn.click()
        page.wait_for_timeout(200)
        assert wrap.evaluate("el => el.classList.contains('is-fullscreen-fallback')") is False

        btn.click()
        page.wait_for_selector(ACTIVE_WRAP + ".is-fullscreen-fallback")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert wrap.evaluate("el => el.classList.contains('is-fullscreen-fallback')") is False
    finally:
        context.close()


def test_fullscreen_fallback_when_webkit_is_noop(origin: str, browser) -> None:
    context, page = _new_page(browser, origin, [_ios_fullscreen_silent_webkit_script()])
    try:
        page.locator(ACTIVE_WRAP + " .map-fs-btn").click()
        page.wait_for_selector(ACTIVE_WRAP + ".is-fullscreen-fallback")
    finally:
        context.close()


def test_gps_marker_from_auto_watch(origin: str, browser) -> None:
    context, page = _new_page(
        browser, origin, [_geo_script(CASCADE_GPS["latitude"], CASCADE_GPS["longitude"])]
    )
    try:
        page.wait_for_selector(".wca-my-location", timeout=5000)
        has_fix = page.locator(".map-loc-btn.has-fix").count()
        assert has_fix >= 1, "locate button did not show a GPS fix"
    finally:
        context.close()


def test_locate_button_recenters_off_map_fix(origin: str, browser) -> None:
    context, page = _new_page(
        browser, origin, [_geo_script(NAMPA_GPS["latitude"], NAMPA_GPS["longitude"])]
    )
    try:
        page.wait_for_selector(".leaflet-container")
        page.locator(ACTIVE_WRAP + " .map-loc-btn").click()
        page.wait_for_selector(".wca-my-location", timeout=5000)
        page.wait_for_timeout(800)
        center = page.evaluate(
            """() => {
              const pane = document.querySelector('.tab-pane.active .map');
              const id = pane && pane.dataset.dayId;
              const m = MAPS && id && MAPS[id];
              if (!m) return null;
              const c = m.getCenter();
              return {lat: c.lat, lng: c.lng};
            }"""
        )
        assert center is not None, "overview map missing after locate"
        assert abs(center["lat"] - NAMPA_GPS["latitude"]) < 0.05, center
        assert abs(center["lng"] - NAMPA_GPS["longitude"]) < 0.05, center
    finally:
        context.close()


def test_high_accuracy_timeout_retries_low_accuracy(origin: str, browser) -> None:
    context, page = _new_page(
        browser,
        origin,
        [_geo_timeout_then_low_accuracy_script(CASCADE_GPS["latitude"], CASCADE_GPS["longitude"])],
    )
    try:
        page.locator(ACTIVE_WRAP + " .map-loc-btn").click()
        page.wait_for_selector(".wca-my-location", timeout=8000)
    finally:
        context.close()


def test_locate_button_touch_target(origin: str, browser) -> None:
    context, page = _new_page(browser, origin, [])
    try:
        box = page.locator(ACTIVE_WRAP + " .map-loc-btn").bounding_box()
        fs = page.locator(ACTIVE_WRAP + " .map-fs-btn").bounding_box()
        assert box and box["height"] >= 44, box
        assert fs and fs["height"] >= 44, fs
    finally:
        context.close()


def test_listen_button_starts_speech_and_stop_cancels(origin: str, browser) -> None:
    context, page = _new_page(browser, origin, [_speech_mock_script()])
    try:
        btn = page.locator(".speak-btn").first
        btn.wait_for()
        name = btn.get_attribute("data-speak-name")
        btn.click()
        page.wait_for_function("() => (window.__WCA_SPOKE || []).some(t => t && t !== '__cancel__')")
        spoke = page.evaluate("() => window.__WCA_SPOKE")
        assert any(name and name in (t or "") for t in spoke), spoke
        page.wait_for_selector("#wca-speak-bar:not([hidden])")
        page.locator("#wca-speak-bar .speak-bar-stop").click()
        page.wait_for_function("() => (window.__WCA_SPOKE || []).includes('__cancel__')")
        hidden = page.evaluate(
            "() => { const b = document.getElementById('wca-speak-bar'); return !b || b.hidden; }"
        )
        assert hidden is True
    finally:
        context.close()


def test_approach_speaks_when_enabled(origin: str, browser) -> None:
    context, page = _new_page(
        browser,
        origin,
        [
            _speech_mock_script(),
            _enable_speak_notes_script(),
            _geo_script(TAKHLAKH_GPS["latitude"], TAKHLAKH_GPS["longitude"]),
        ],
    )
    try:
        page.wait_for_function(
            "() => (window.__WCA_SPOKE || []).some(t => t && String(t).indexOf('Takhlakh') !== -1)",
            timeout=8000,
        )
        page.wait_for_selector("#wca-speak-bar:not([hidden])")
    finally:
        context.close()


def test_settings_persist_and_voice_sample(origin: str, browser) -> None:
    context, page = _new_context(browser, [_speech_mock_script()])
    try:
        page.goto(origin + "/settings.html", wait_until="domcontentloaded")
        page.wait_for_selector("#speak-enabled")
        page.locator("#speak-enabled").check()
        page.locator('input[name="speak-scope"][value="included"]').check()
        page.locator("#speak-landmarks").uncheck()
        page.locator("#speak-repeat").check()
        page.wait_for_function("() => document.querySelector('#speak-voice').options.length >= 2")
        net_key = "Network Voice|en-GB|net-en"
        page.select_option("#speak-voice", net_key)
        page.wait_for_function(
            "() => (window.__WCA_SPOKE || []).some(t => t && String(t).indexOf('Washington Cascades') !== -1)"
        )
        last = page.evaluate("() => window.__WCA_LAST_UTTERANCE")
        assert last and last.get("name") == "Network Voice", last
        assert last.get("lang") == "en-GB", last
        stored = page.evaluate(
            """() => ({
              enabled: localStorage.getItem('wca-speak-notes'),
              scope: localStorage.getItem('wca-speak-notes-scope'),
              landmarks: localStorage.getItem('wca-speak-notes-landmarks'),
              repeat: localStorage.getItem('wca-speak-notes-repeat'),
              voice: localStorage.getItem('wca-speak-notes-voice'),
            })"""
        )
        assert stored["enabled"] == "1", stored
        assert stored["scope"] == "included", stored
        assert stored["landmarks"] == "0", stored
        assert stored["repeat"] == "1", stored
        assert stored["voice"] == net_key, stored

        page.goto(origin + "/trip-itinerary.html", wait_until="domcontentloaded")
        page.wait_for_selector(".leaflet-container", timeout=30000)
        flags = page.evaluate("() => window.WcaSpeakSettings && WcaSpeakSettings.read()")
        assert flags["enabled"] is True
        assert flags["scope"] == "included"
        assert flags["landmarks"] is False
        assert flags["repeat"] is True
        assert flags["voice"] == "Network Voice|en-GB|net-en"
    finally:
        context.close()


def _android_blank_uri_voices_script() -> str:
    """Android Chrome often exposes several voices with an empty voiceURI."""
    return """
    (function() {
      window.__WCA_SPOKE = [];
      window.__WCA_VOICES = [
        {name:'English United States', lang:'en-US', localService:false, default:true, voiceURI:''},
        {name:'English United Kingdom', lang:'en-GB', localService:false, default:false, voiceURI:''}
      ];
      function Utterance(text) {
        this.text = text; this.voice = null; this.rate = 1; this.volume = 1; this.lang = '';
      }
      const synth = {
        speaking: false, paused: false, pending: false, _current: null,
        getVoices: function() { return window.__WCA_VOICES; },
        speak: function(u) {
          window.__WCA_SPOKE.push(u && u.text);
          window.__WCA_LAST_UTTERANCE = {
            text: u && u.text,
            voiceURI: u && u.voice && u.voice.voiceURI,
            lang: u && u.lang,
            name: u && u.voice && u.voice.name
          };
          this.speaking = true; this._current = u;
        },
        cancel: function() { this.speaking = false; this._current = null; },
        pause: function() {}, resume: function() {},
        addEventListener: function() {}, removeEventListener: function() {}
      };
      window.SpeechSynthesisUtterance = Utterance;
      Object.defineProperty(window, 'speechSynthesis', {
        configurable: true, get: function() { return synth; }
      });
    })();
    """


def test_android_blank_voiceuri_uses_selected_voice(origin: str, browser) -> None:
    context, page = _new_context(browser, [_android_blank_uri_voices_script()])
    try:
        page.goto(origin + "/settings.html", wait_until="domcontentloaded")
        page.wait_for_function("() => document.querySelector('#speak-voice').options.length >= 2")
        page.select_option("#speak-voice", value="English United Kingdom|en-GB|")
        page.wait_for_function("() => window.__WCA_LAST_UTTERANCE && window.__WCA_LAST_UTTERANCE.name")
        last = page.evaluate("() => window.__WCA_LAST_UTTERANCE")
        assert last["name"] == "English United Kingdom", last
        assert last["lang"] == "en-GB", last
    finally:
        context.close()


def _run_playwright(origin: str) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright is not installed. Static checks passed.\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium\n"
            "  python scripts/test_ipad_maps.py"
        )
        sys.exit(0)

    with sync_playwright() as pw:
        try:
            pw.chromium.launch(headless=True).close()
        except Exception as exc:
            print(
                "Playwright Chromium is not installed:\n"
                "  python -m playwright install chromium\n"
                f"({exc})"
            )
            sys.exit(1)

        tests = [
            ("fullscreen fallback when API disabled", test_fullscreen_fallback_when_api_disabled),
            ("fullscreen fallback when webkit is a no-op", test_fullscreen_fallback_when_webkit_is_noop),
            ("GPS marker from auto-watch", test_gps_marker_from_auto_watch),
            ("locate button recenters off-map fix", test_locate_button_recenters_off_map_fix),
            ("high-accuracy timeout retries low accuracy", test_high_accuracy_timeout_retries_low_accuracy),
            ("locate/fullscreen 44px touch targets", test_locate_button_touch_target),
            ("Listen button speaks and Stop cancels", test_listen_button_starts_speech_and_stop_cancels),
            ("approach speaks when enabled", test_approach_speaks_when_enabled),
            ("Settings persist and voice sample", test_settings_persist_and_voice_sample),
            ("Android blank voiceURI uses selected voice", test_android_blank_voiceuri_uses_selected_voice),
        ]
        browser = pw.chromium.launch(headless=True)
        failed = []
        try:
            for name, fn in tests:
                try:
                    fn(origin, browser)
                    print(f"  PASS  {name}")
                except Exception as exc:
                    print(f"  FAIL  {name}: {exc}")
                    failed.append(name)
        finally:
            browser.close()
        if failed:
            raise AssertionError("Playwright failures: " + ", ".join(failed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Skip Playwright (still checks the generated HTML contains the fixes).",
    )
    args = parser.parse_args()

    print("Static checks on trip-itinerary.html")
    test_static_fixes_present()
    print("  PASS  generated HTML includes iPad GPS + fullscreen + spoken-notes hooks")
    test_static_settings_page()
    print("  PASS  settings.html includes Spoken notes controls")

    if args.static_only:
        return 0

    httpd, origin = _serve(ROOT)
    try:
        print(f"Playwright iPad emulation against {origin}")
        _run_playwright(origin)
    finally:
        httpd.shutdown()
        httpd.server_close()
    print("All iPad map tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
