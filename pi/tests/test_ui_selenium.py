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
            "metrics_csv_path": str(tmp_dir / "metrics.csv"),
            "metrics_log_hz": 4,
        },
        "storage": {"clients_json_path": str(persist_path)},
        "gps": {"gps_enabled": False, "gps_speed_only": True},
    }
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    pi_dir = Path(__file__).resolve().parents[1]
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
    wait.until(
        lambda d: d.execute_script(
            script,
            view_id
        )
    )


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

    _activate_tab(driver, "tab-logs", "logsView")
    _activate_tab(driver, "tab-report", "reportView")
    _activate_tab(driver, "tab-settings", "settingsView")
    _activate_tab(driver, "tab-dashboard", "dashboardView")


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

    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "row-location-select")))
    wait.until(
        lambda d: len(
            d.execute_script(
                "const s=document.querySelector('.row-location-select');"
                "return s ? Array.from(s.options).map(o=>o.text.trim()) : [];",
            ),
        )
        > 10,
    )
    labels = driver.execute_script(
        "const s=document.querySelector('.row-location-select');"
        "return s ? Array.from(s.options).map(o=>o.text.trim()) : [];",
    )
    assert "Front Left Wheel" in labels
    assert "Transmission" in labels
    assert "Driver Seat" in labels
    assert "Trunk" in labels


def test_offline_client_mac_set_location_and_remove(
    driver: webdriver.Remote,
    live_server: dict[str, object],
) -> None:
    base_url = str(live_server["base_url"])
    driver.get(f"{base_url}/")
    wait = WebDriverWait(driver, 10)
    _activate_tab(driver, "tab-settings", "settingsView")

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
        lambda d: d.execute_script(
            "const el=document.querySelector(arguments[0] + ' td strong');"
            "return el ? el.textContent.trim() : '';",
            row_selector,
        )
        == "Trunk"
    )

    driver.execute_script("window.confirm = () => true;")
    remove_btn = (By.CSS_SELECTOR, f"{row_selector} .row-remove")
    wait.until(EC.element_to_be_clickable(remove_btn)).click()
    wait.until(
        lambda d: d.execute_script(
            "return document.querySelector(arguments[0]) === null;",
            row_selector,
        )
    )
