from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import yaml

pytest.importorskip("selenium", reason="selenium is not installed")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

pytestmark = pytest.mark.selenium


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http_ok(url: str, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except (URLError, OSError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError(f"Server did not become ready: {url}")


@pytest.fixture(scope="module")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    pi_dir = Path(__file__).resolve().parents[1]
    if not (pi_dir / "public" / "index.html").exists():
        pytest.skip("Selenium UI tests require built apps/server/public assets")
    tmp_dir = tmp_path_factory.mktemp("selenium-ui")
    port = _free_port()
    data_port = _free_port()
    control_port = _free_port()
    if control_port == data_port:
        control_port = _free_port()
    config_path = tmp_dir / "config.selenium.yaml"
    persist_path = tmp_dir / "clients.json"
    persist_path.write_text(
        json.dumps(
            {
                "clients": [
                    {
                        "id": "d05a00000099",
                        "name": "offline-node",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cfg = {
        "server": {"host": "127.0.0.1", "port": port},
        "udp": {
            "data_listen": f"127.0.0.1:{data_port}",
            "control_listen": f"127.0.0.1:{control_port}",
        },
        "logging": {
            "log_metrics": False,
            "metrics_log_path": str(tmp_dir / "metrics.jsonl"),
            "metrics_log_hz": 4,
        },
        "storage": {"clients_json_path": str(persist_path)},
        "gps": {"gps_enabled": False, "gps_speed_only": True},
    }
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "vibesensor.app", "--config", str(config_path)],
        cwd=str(pi_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_http_ok(f"{base_url}/")
        yield {"base_url": base_url, "control_port": control_port}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture()
def driver() -> webdriver.Remote:
    errors: list[str] = []

    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,1000")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        drv = webdriver.Chrome(options=options)
        try:
            yield drv
            return
        finally:
            drv.quit()
    except Exception as exc:  # pragma: no cover - depends on host browser availability
        errors.append(f"chrome: {exc}")

    try:
        options = webdriver.FirefoxOptions()
        options.add_argument("-headless")
        drv = webdriver.Firefox(options=options)
        try:
            yield drv
            return
        finally:
            drv.quit()
    except Exception as exc:  # pragma: no cover - depends on host browser availability
        errors.append(f"firefox: {exc}")

    pytest.skip("No Selenium-compatible browser driver available: " + " | ".join(errors))


def _activate_tab(driver: webdriver.Remote, tab_id: str, view_id: str) -> None:
    wait = WebDriverWait(driver, 10)
    wait.until(EC.element_to_be_clickable((By.ID, tab_id))).click()
    script = (
        "const v=document.getElementById(arguments[0]); "
        "return v && v.classList.contains('active') && !v.hidden;"
    )
    wait.until(lambda d: d.execute_script(script, view_id))


def _activate_settings_subtab(driver: webdriver.Remote, tab_id: str) -> None:
    wait = WebDriverWait(driver, 10)
    selector = f'[data-settings-tab="{tab_id}"]'
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector))).click()
    wait.until(
        lambda d: not d.execute_script(
            "const el=document.getElementById(arguments[0]); return el ? el.hidden : true;",
            tab_id,
        )
    )


def _set_language(driver: webdriver.Remote, lang: str) -> None:
    wait = WebDriverWait(driver, 10)
    select = wait.until(EC.presence_of_element_located((By.ID, "languageSelect")))
    driver.execute_script(
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
        select,
        lang,
    )
    wait.until(lambda d: d.execute_script("return document.documentElement.lang;") == lang)


def _seed_client_hello(control_port: int) -> None:
    from vibesensor.protocol import pack_hello

    packet = pack_hello(
        client_id=bytes.fromhex("001122334455"),
        control_port=9010,
        sample_rate_hz=800,
        name="seed-client",
        firmware_version="sim-seed",
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _ in range(3):
            sock.sendto(packet, ("127.0.0.1", control_port))
            time.sleep(0.1)


def test_nav_tabs_switch_views(driver: webdriver.Remote, live_server: dict[str, object]) -> None:
    base_url = str(live_server["base_url"])
    driver.get(f"{base_url}/")
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "tab-dashboard")))

    _activate_tab(driver, "tab-history", "historyView")
    _activate_tab(driver, "tab-settings", "settingsView")
    _activate_tab(driver, "tab-dashboard", "dashboardView")


@pytest.mark.parametrize(
    ("lang", "labels"),
    [
        (
            "en",
            {
                "nav": ["Live", "History", "Settings"],
                "start_recording": "Start Recording",
                "refresh_history": "Refresh History",
                "save_analysis": "Save Analysis Settings",
                "settings_location_header": "Location",
            },
        ),
        (
            "nl",
            {
                "nav": ["Live", "Geschiedenis", "Instellingen"],
                "start_recording": "Opname starten",
                "refresh_history": "Geschiedenis verversen",
                "save_analysis": "Analyse-instellingen opslaan",
                "settings_location_header": "Locatie",
            },
        ),
    ],
)
def test_all_tabs_render_localized_texts(
    driver: webdriver.Remote,
    live_server: dict[str, object],
    lang: str,
    labels: dict[str, object],
) -> None:
    base_url = str(live_server["base_url"])
    driver.get(f"{base_url}/")
    wait = WebDriverWait(driver, 10)
    _set_language(driver, lang)

    nav_texts = driver.execute_script(
        "const nodes = Array.from(document.querySelectorAll('.menu-btn span'));"
        "return nodes.map((el) => el.textContent.trim());"
    )
    assert nav_texts == labels["nav"]

    _activate_tab(driver, "tab-dashboard", "dashboardView")
    wait.until(
        lambda d: d.find_element(By.ID, "startLoggingBtn").text.strip() == labels["start_recording"]
    )

    _activate_tab(driver, "tab-history", "historyView")
    wait.until(
        lambda d: (
            d.find_element(By.ID, "refreshHistoryBtn").text.strip()
            == labels["refresh_history"]
        )
    )

    _activate_tab(driver, "tab-settings", "settingsView")
    _activate_settings_subtab(driver, "analysisTab")
    wait.until(
        lambda d: d.find_element(By.ID, "saveAnalysisBtn").text.strip() == labels["save_analysis"]
    )
    _activate_settings_subtab(driver, "sensorsTab")
    headers = driver.execute_script(
        "const headers = Array.from(document.querySelectorAll('.clients-table thead th'));"
        "return headers.map((el) => el.textContent.trim());"
    )
    # The location column label must localize correctly in both languages.
    assert labels["settings_location_header"] in headers


def test_logging_buttons_toggle_status_badge(
    driver: webdriver.Remote,
    live_server: dict[str, object],
) -> None:
    base_url = str(live_server["base_url"])
    driver.get(f"{base_url}/")
    wait = WebDriverWait(driver, 10)
    _activate_tab(driver, "tab-dashboard", "dashboardView")

    wait.until(EC.element_to_be_clickable((By.ID, "startLoggingBtn"))).click()
    wait.until(lambda d: d.find_element(By.ID, "loggingStatus").text.strip() == "Running")

    wait.until(EC.element_to_be_clickable((By.ID, "stopLoggingBtn"))).click()
    wait.until(lambda d: d.find_element(By.ID, "loggingStatus").text.strip() == "Stopped")


def test_location_selector_has_vehicle_positions(
    driver: webdriver.Remote,
    live_server: dict[str, object],
) -> None:
    base_url = str(live_server["base_url"])
    control_port = int(live_server["control_port"])
    _seed_client_hello(control_port)
    driver.get(f"{base_url}/")
    wait = WebDriverWait(driver, 10)
    _activate_tab(driver, "tab-settings", "settingsView")
    _activate_settings_subtab(driver, "sensorsTab")

    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "row-location-select")))
    wait.until(
        lambda d: (
            len(
                d.execute_script(
                    "const s=document.querySelector('.row-location-select');"
                    "return s ? Array.from(s.options).map(o=>o.text.trim()) : [];",
                ),
            )
            > 10
        ),
    )
    labels = driver.execute_script(
        "const s=document.querySelector('.row-location-select');"
        "return s ? Array.from(s.options).map(o=>o.text.trim()) : [];",
    )
    assert "Front Left Wheel" in labels
    assert "Transmission" in labels
    assert "Driver Seat" in labels
    assert "Trunk" in labels


def test_logs_can_be_deleted_with_confirmation(
    driver: webdriver.Remote,
    live_server: dict[str, object],
) -> None:
    base_url = str(live_server["base_url"])
    driver.get(f"{base_url}/")
    wait = WebDriverWait(driver, 10)
    _activate_tab(driver, "tab-dashboard", "dashboardView")

    wait.until(EC.element_to_be_clickable((By.ID, "startLoggingBtn"))).click()
    wait.until(lambda d: d.find_element(By.ID, "loggingStatus").text.strip() == "Running")
    wait.until(EC.element_to_be_clickable((By.ID, "stopLoggingBtn"))).click()
    wait.until(lambda d: d.find_element(By.ID, "loggingStatus").text.strip() == "Stopped")

    _activate_tab(driver, "tab-history", "historyView")
    del_sel = '[data-run-action="delete-run"]'
    wait.until(
        lambda d: (
            d.execute_script(
                "return document.querySelectorAll(arguments[0]).length;",
                del_sel,
            )
            >= 1
        )
    )
    before_count = int(
        driver.execute_script(
            "return document.querySelectorAll(arguments[0]).length;",
            del_sel,
        )
    )
    assert before_count >= 1

    driver.execute_script("window.confirm = () => true;")
    driver.execute_script(
        "const btn=document.querySelector(arguments[0]);"
        " if (btn) btn.click();",
        del_sel,
    )
    wait.until(
        lambda d: (
            d.execute_script(
                "return document.querySelectorAll(arguments[0]).length;",
                del_sel,
            )
            == max(0, before_count - 1)
        )
    )


def test_dutch_logs_uses_domain_terms_not_literal_calque(
    driver: webdriver.Remote,
    live_server: dict[str, object],
) -> None:
    base_url = str(live_server["base_url"])
    wait = WebDriverWait(driver, 10)
    driver.get(f"{base_url}/")
    _activate_tab(driver, "tab-dashboard", "dashboardView")

    wait.until(EC.element_to_be_clickable((By.ID, "startLoggingBtn"))).click()
    wait.until(lambda d: d.find_element(By.ID, "loggingStatus").text.strip() == "Running")
    wait.until(EC.element_to_be_clickable((By.ID, "stopLoggingBtn"))).click()
    wait.until(lambda d: d.find_element(By.ID, "loggingStatus").text.strip() == "Stopped")

    _set_language(driver, "nl")
    _activate_tab(driver, "tab-history", "historyView")
    del_sel = '[data-run-action="delete-run"]'
    wait.until(
        lambda d: (
            d.execute_script(
                "return document.querySelectorAll(arguments[0]).length;",
                del_sel,
            )
            >= 1
        )
    )

    # The Dutch history table header should use "Meetrun" (domain term) not a literal calque.
    headers = driver.execute_script(
        "const ths = Array.from("
        "document.querySelectorAll('.history-table thead th'));"
        "return ths.map((th) => th.textContent.trim());"
    )
    assert "Meetrun" in headers

    # Export action buttons should use "Exporteren" (proper Dutch) not a calque.
    raw_sel = '#historyTableBody [data-run-action="download-raw"]'
    action_labels = driver.execute_script(
        "const btns = Array.from("
        "document.querySelectorAll(arguments[0]));"
        "return btns.map((b) => b.textContent.trim());",
        raw_sel,
    )
    assert any(label == "Exporteren" for label in action_labels)
    assert all(label != "Uitvoer" for label in action_labels)


def test_offline_client_mac_set_location_and_remove(
    driver: webdriver.Remote,
    live_server: dict[str, object],
) -> None:
    base_url = str(live_server["base_url"])
    driver.get(f"{base_url}/")
    wait = WebDriverWait(driver, 10)
    _activate_tab(driver, "tab-settings", "settingsView")
    _activate_settings_subtab(driver, "sensorsTab")

    row_selector = "tr[data-client-id='d05a00000099']"
    wait.until(
        lambda d: d.execute_script(
            "return !!document.querySelector(arguments[0]);",
            row_selector,
        )
    )

    mac_text = driver.execute_script(
        "const el=document.querySelector(arguments[0] + ' td:nth-child(2) code');"
        "return el ? el.textContent.trim() : '';",
        row_selector,
    )
    assert mac_text == "d0:5a:00:00:00:99"

    driver.execute_script(
        "const s=document.querySelector(arguments[0] + ' .row-location-select');"
        "if(s){s.value='trunk'; s.dispatchEvent(new Event('change', {bubbles:true}));}",
        row_selector,
    )
    wait.until(
        lambda d: (
            d.execute_script(
                "const el=document.querySelector(arguments[0] + ' td strong');"
                "return el ? el.textContent.trim() : '';",
                row_selector,
            )
            == "Trunk"
        )
    )

    driver.execute_script("window.confirm = () => true;")
    remove_selector = f"{row_selector} .row-remove"
    wait.until(
        lambda d: d.execute_script(
            "const btn=document.querySelector(arguments[0]);"
            "if(!btn) return false;"
            "btn.click();"
            "return true;",
            remove_selector,
        )
    )
    wait.until(
        lambda d: d.execute_script(
            "return document.querySelector(arguments[0]) === null;",
            row_selector,
        )
    )
