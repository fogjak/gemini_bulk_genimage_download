import os
import time
import argparse
import msvcrt
import configparser
import re
import subprocess
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    JavascriptException,
    NoSuchWindowException,
    StaleElementReferenceException,
    WebDriverException,
)


DOWNLOAD_BUTTON_XPATH = (
    "//button["
    "not(@disabled) and not(@aria-disabled='true') and ("
    "contains(@aria-label, '원본 크기 이미지 다운로드') or "
    "(contains(@aria-label, '이미지') and contains(@aria-label, '다운로드')) or "
    "(contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') "
    " and contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'image')) or "
    ".//mat-icon[@data-mat-icon-name='download' or @fonticon='download']"
    ")]"
)

PROGRESS_SELECTOR = (
    "mat-spinner, mat-progress-spinner, [role='progressbar'], "
    "[class*='spinner'], [class*='progress'], [class*='loading']"
)


BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "autodown.log"


@dataclass
class ProtectedFile:
    original: Path
    temporary: Path


def setup_console():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(os.sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def log(message):
    print(message, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def load_config():
    """config.conf 파일에서 디버깅 포트를 읽어옵니다. 파일이 없거나 오류가 있으면 기본값 9222를 반환합니다."""
    config = configparser.ConfigParser()
    default_port = 9222

    try:
        config.read("config.conf", encoding="utf-8")
        if "options" in config and "debugging-port" in config["options"]:
            return int(config["options"]["debugging-port"])
    except Exception:
        pass

    return default_port


def connect_chrome(debug_port):
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
    return webdriver.Chrome(options=chrome_options)


def get_devtools_version(debug_port, timeout=1.0):
    url = f"http://127.0.0.1:{debug_port}/json/version"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def wait_for_debug_port(debug_port, max_wait=5.0):
    deadline = time.time() + max_wait
    last_error = None

    while time.time() < deadline:
        try:
            return get_devtools_version(debug_port)
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.3)

    raise RuntimeError(f"127.0.0.1:{debug_port} DevTools 포트에 연결할 수 없습니다. 마지막 오류: {last_error}")


def local_listening_ports():
    try:
        output = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
    except Exception:
        return []

    ports = set()
    for line in output.splitlines():
        if "LISTENING" not in line:
            continue

        matches = re.findall(r"(?:127\.0\.0\.1|\[::1\]):(\d+)", line)
        for match in matches:
            try:
                ports.add(int(match))
            except ValueError:
                pass

    return sorted(ports)


def find_devtools_ports(exclude_port=None):
    found = []
    for port in local_listening_ports():
        if port == exclude_port:
            continue

        try:
            version_text = get_devtools_version(port, timeout=0.25)
        except Exception:
            continue

        if "Chrome/" in version_text or "Chromium/" in version_text:
            found.append((port, version_text))

    return found


def switch_to_gemini_tab(driver):
    """여러 탭이 열려 있어도 gemini.google.com/app 탭을 우선 사용합니다."""
    preferred_handle = None
    fallback_handle = None

    for handle in driver.window_handles:
        try:
            driver.switch_to.window(handle)
            url = driver.current_url or ""
        except (NoSuchWindowException, WebDriverException):
            continue

        if "gemini.google.com/app" in url:
            preferred_handle = handle
            break
        if "gemini.google.com" in url:
            fallback_handle = handle

    target_handle = preferred_handle or fallback_handle
    if target_handle:
        driver.switch_to.window(target_handle)
        return True

    return False


def get_download_dir(driver):
    """Chrome 설정에서 기본 다운로드 경로를 읽고, 실패하면 ~/Downloads를 사용합니다."""
    fallback = Path.home() / "Downloads"
    try:
        result = driver.execute_cdp_cmd(
            "Browser.getVersion",
            {},
        )
        # Browser.getVersion 자체는 경로를 주지 않지만 CDP 연결 확인 용도로 둡니다.
        if result:
            return fallback
    except Exception:
        pass
    return fallback


def allow_downloads(driver, download_dir):
    params = {"behavior": "allow", "downloadPath": str(download_dir)}
    try:
        driver.execute_cdp_cmd("Page.setDownloadBehavior", params)
    except Exception:
        driver.execute_cdp_cmd("Browser.setDownloadBehavior", params)


def get_download_buttons(driver):
    """현재 Gemini DOM에서 생성 이미지 다운로드 버튼만 모아 문서 순서대로 반환합니다."""
    script = """
        const xpath = arguments[0];
        const snapshot = document.evaluate(
            xpath,
            document,
            null,
            XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
            null
        );
        const seen = new Set();
        const buttons = [];

        for (let i = 0; i < snapshot.snapshotLength; i += 1) {
            const button = snapshot.snapshotItem(i);
            if (!button || seen.has(button)) continue;
            seen.add(button);

            const label = button.getAttribute('aria-label') || '';
            const icon = button.querySelector('mat-icon[data-mat-icon-name="download"], mat-icon[fonticon="download"]');
            const imageHost = button.closest(
                'generated-image-controls, .generated-image-controls, generated-image, image-carousel, ' +
                '.image-container, [class*="generated-image"], [class*="image"]'
            );

            const looksLikeImageDownload =
                label.includes('원본 크기 이미지 다운로드') ||
                (label.includes('이미지') && label.includes('다운로드')) ||
                (/image/i.test(label) && /download/i.test(label)) ||
                (icon && imageHost);

            if (!looksLikeImageDownload) continue;
            if (button.disabled || button.getAttribute('aria-disabled') === 'true') continue;

            const rect = button.getBoundingClientRect();
            buttons.push({
                element: button,
                top: rect.top + window.scrollY,
                left: rect.left + window.scrollX,
                domIndex: i
            });
        }

        buttons.sort((a, b) => (a.top - b.top) || (a.left - b.left) || (a.domIndex - b.domIndex));
        return buttons.map(item => item.element);
    """
    try:
        buttons = driver.execute_script(script, DOWNLOAD_BUTTON_XPATH)
    except JavascriptException:
        buttons = driver.find_elements(By.XPATH, DOWNLOAD_BUTTON_XPATH)

    return buttons or []


def describe_button(button):
    try:
        label = button.get_attribute("aria-label") or "다운로드"
        return label.strip()
    except Exception:
        return "다운로드"


def scroll_button_into_view(driver, button):
    driver.execute_script(
        """
        arguments[0].scrollIntoView({behavior: 'instant', block: 'center', inline: 'center'});
        """,
        button,
    )
    time.sleep(0.6)


def click_button(driver, button):
    try:
        ActionChains(driver).move_to_element(button).pause(0.1).click(button).perform()
    except (ElementClickInterceptedException, WebDriverException):
        driver.execute_script("arguments[0].click();", button)


def download_snapshot(download_dir):
    state = {}
    try:
        for path in download_dir.iterdir():
            if not path.is_file():
                continue
            if path.name.endswith(".crdownload"):
                continue
            stat = path.stat()
            state[str(path)] = (stat.st_size, stat.st_mtime_ns)
    except FileNotFoundError:
        download_dir.mkdir(parents=True, exist_ok=True)
    return state


def active_chrome_downloads(download_dir):
    try:
        return [path for path in download_dir.iterdir() if path.name.endswith(".crdownload")]
    except FileNotFoundError:
        return []


def is_probable_chrome_temp_name(path):
    return path.name.endswith(".crdownload") and not path.name.startswith("Unconfirmed ")


def final_path_from_crdownload(path):
    if not is_probable_chrome_temp_name(path):
        return None
    return path.with_name(path.name[: -len(".crdownload")])


def numbered_path(path, occupied_paths=None):
    occupied = {Path(item).resolve() for item in (occupied_paths or [])}

    def is_occupied(candidate):
        resolved = candidate.resolve() if candidate.exists() else candidate.absolute()
        return candidate.exists() or resolved in occupied

    if not is_occupied(path):
        return path

    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not is_occupied(candidate):
            return candidate

    raise RuntimeError(f"사용 가능한 중복 파일명을 만들 수 없습니다: {path}")


def make_preserve_path(path):
    preserve_dir = path.parent / ".autodown_preserve"
    preserve_dir.mkdir(exist_ok=True)
    return preserve_dir / f"{time.time_ns()}_{path.name}"


def protect_existing_file(path, protected_files, quiet=False):
    path = Path(path)
    if path in protected_files:
        return
    if not path.exists() or not path.is_file():
        return

    temporary = make_preserve_path(path)
    path.replace(temporary)
    protected_files[path] = ProtectedFile(original=path, temporary=temporary)
    if not quiet:
        log(f"중복 파일명 보호: {path.name}")


def protect_active_download_targets(download_dir, protected_files):
    for temp_path in active_chrome_downloads(download_dir):
        final_path = final_path_from_crdownload(temp_path)
        if final_path is not None:
            protect_existing_file(final_path, protected_files)


def restore_protected_files(protected_files):
    for protected in list(protected_files.values()):
        if protected.temporary.exists() and not protected.original.exists():
            protected.temporary.replace(protected.original)
    cleanup_preserve_dir(protected_files)


def cleanup_preserve_dir(protected_files):
    preserve_dirs = {item.temporary.parent for item in protected_files.values()}
    for preserve_dir in preserve_dirs:
        remove_empty_dir(preserve_dir)


def remove_empty_dir(path):
    try:
        path.rmdir()
    except OSError:
        pass


def finalize_duplicate_download(downloaded_path, protected_files):
    downloaded_path = Path(downloaded_path)
    protected = protected_files.get(downloaded_path)
    if protected is None:
        return downloaded_path

    new_path = numbered_path(downloaded_path, occupied_paths=[downloaded_path])
    downloaded_path.replace(new_path)
    protected.temporary.replace(protected.original)
    preserve_dir = protected.temporary.parent
    del protected_files[downloaded_path]
    remove_empty_dir(preserve_dir)
    log(f"중복 파일명 저장: {new_path.name}")
    return new_path


def changed_downloads(download_dir, before):
    after = download_snapshot(download_dir)
    changed = []
    for path, value in after.items():
        if path not in before or before[path] != value:
            changed.append(Path(path))
    changed.sort(key=lambda item: item.stat().st_mtime_ns if item.exists() else 0, reverse=True)
    return changed


def wait_until_file_stable(path, seconds=1.0):
    last_size = -1
    stable_since = time.time()

    while time.time() - stable_since < seconds:
        if not path.exists():
            return False

        size = path.stat().st_size
        if size != last_size:
            last_size = size
            stable_since = time.time()
        time.sleep(0.2)

    return True


def has_button_progress(button):
    try:
        return len(button.find_elements(By.CSS_SELECTOR, PROGRESS_SELECTOR)) > 0
    except Exception:
        return False


def check_keyboard_for_control():
    if not msvcrt.kbhit():
        return None

    key = msvcrt.getch()
    if key == b"\x0e":  # Ctrl+N
        return "skip"
    if key == b"\x03":  # Ctrl+C
        raise KeyboardInterrupt
    return None


def wait_for_download_complete(driver, download_dir, before, button_index, total, protected_files, max_wait=90):
    wait_start = time.time()
    saw_progress = False
    saw_download_file = False
    last_status_at = 0

    while time.time() - wait_start < max_wait:
        control = check_keyboard_for_control()
        if control == "skip":
            return "skipped", None

        elapsed = time.time() - wait_start
        active = active_chrome_downloads(download_dir)
        if active:
            saw_download_file = True
            protect_active_download_targets(download_dir, protected_files)
            if time.time() - last_status_at > 0.5:
                print(
                    f"[{button_index}/{total}] 다운로드 진행 중... "
                    f"({len(active)}개 임시 파일)     ",
                    end="\r",
                )
                last_status_at = time.time()
            time.sleep(0.4)
            continue

        changed = changed_downloads(download_dir, before)
        if changed and wait_until_file_stable(changed[0]):
            return "completed", finalize_duplicate_download(changed[0], protected_files)

        buttons = get_download_buttons(driver)
        current_button = buttons[button_index - 1] if button_index - 1 < len(buttons) else None
        if current_button is not None and has_button_progress(current_button):
            saw_progress = True
            if time.time() - last_status_at > 0.5:
                print(f"[{button_index}/{total}] 다운로드 준비 중... (페이지 진행 표시 감지)     ", end="\r")
                last_status_at = time.time()
            time.sleep(0.4)
            continue

        if saw_progress and elapsed > 1.5:
            return "ui_completed", None

        if saw_download_file and elapsed > 1.5:
            return "completed_without_new_file", None

        time.sleep(0.4)

    return "timeout", None


def download_gemini_images():
    setup_console()
    log("Gemini Image Auto Downloader 시작")

    parser = argparse.ArgumentParser(description="Gemini Image Auto Downloader")
    parser.add_argument("-c", type=int, default=1, help="Start from Nth image (1-based index)")
    parser.add_argument("-l", type=int, default=0, help="Limit number of downloads (0 for all)")
    parser.add_argument("-w", type=int, default=90, help="Max seconds to wait for each download")
    args = parser.parse_args()

    start_index = args.c - 1
    if start_index < 0:
        log("오류: 시작 인덱스(-c)는 1 이상이어야 합니다.")
        return

    limit_count = args.l
    if limit_count < 0:
        log("오류: 개수 제한(-l)은 0 이상이어야 합니다.")
        return

    debug_port = load_config()
    log(f"디버그 포트 확인: {debug_port}")

    try:
        log("Chrome DevTools 포트 응답 확인 중...")
        try:
            version_text = wait_for_debug_port(debug_port)
        except Exception as port_exc:
            log(f"설정된 포트({debug_port}) 응답 없음: {port_exc}")
            log("다른 로컬 DevTools 포트 자동 탐색 중...")
            candidates = find_devtools_ports(exclude_port=debug_port)
            if not candidates:
                raise port_exc

            debug_port, version_text = candidates[0]
            log(f"DevTools 포트 자동 발견: {debug_port}")

        log(f"Chrome DevTools 응답 확인 완료: {version_text[:120].replace(chr(10), ' ')}")
        log("ChromeDriver 연결 시작...")
        driver = connect_chrome(debug_port)
        log("ChromeDriver 연결 완료")
    except Exception as exc:
        log(f"오류: 디버깅 모드 크롬 연결 실패. (포트: {debug_port})")
        log(f"상세 오류: {exc}")
        log("Chrome을 디버그 모드로 실행했는지 확인하세요.")
        return

    if not switch_to_gemini_tab(driver):
        log("오류: 열린 Chrome 탭에서 gemini.google.com 페이지를 찾지 못했습니다.")
        log("다운로드할 Gemini 대화 페이지를 먼저 열어 주세요.")
        return

    download_dir = get_download_dir(driver)
    allow_downloads(driver, download_dir)

    log(f"저장 경로: {download_dir}")
    log(f"브라우저 연결 성공! 디버그 포트: {debug_port}")
    log(f"Gemini 탭: {driver.title}")
    log("사용법: [Ctrl+C] 종료 | [Ctrl+N] 현재 항목 건너뛰기")

    time.sleep(1.0)
    buttons = get_download_buttons(driver)

    if not buttons:
        log("다운로드 버튼을 찾을 수 없습니다.")
        log("대화 페이지에서 이미지가 로드되어 있는지, 생성 이미지 하단 버튼이 보이는지 확인해 주세요.")
        return

    total_elements = len(buttons)
    end_index = total_elements
    if limit_count > 0:
        end_index = min(start_index + limit_count, total_elements)

    if start_index >= total_elements:
        log(f"오류: 시작 번호({args.c})가 총 이미지 수({total_elements})보다 큽니다.")
        return

    process_count = end_index - start_index
    log(f"총 {total_elements}개의 이미지 다운로드 버튼 발견.")
    if limit_count > 0:
        log(f"{args.c}번째부터 {process_count}개만 다운로드합니다. (범위: {args.c}~{end_index})")
    else:
        log(f"{args.c}번째부터 끝까지 다운로드합니다.")
    log("-" * 50)

    total_start_time = time.time()
    success_count = 0
    skipped_count = 0
    run_downloaded_paths = []
    current_protected_files = {}

    try:
        for i in range(start_index, end_index):
            button_number = i + 1
            protected_files = {}
            current_protected_files = protected_files

            try:
                control = check_keyboard_for_control()
                if control == "skip":
                    log(f"[{button_number}/{total_elements}] 사용자 요청으로 건너뜁니다.")
                    skipped_count += 1
                    continue

                current_buttons = get_download_buttons(driver)
                total_elements = max(total_elements, len(current_buttons))
                if i >= len(current_buttons):
                    log(f"[{button_number}] 버튼을 찾을 수 없습니다. (페이지 목록 변경됨)")
                    break

                button = current_buttons[i]
                label = describe_button(button)

                scroll_button_into_view(driver, button)

                for previous_path in run_downloaded_paths:
                    protect_existing_file(previous_path, protected_files, quiet=True)

                before = download_snapshot(download_dir)
                click_start = time.time()
                click_button(driver, button)
                print(f"[{button_number}/{total_elements}] {label} 요청 완료. 상태 확인 중...", end="\r")

                status, downloaded_path = wait_for_download_complete(
                    driver,
                    download_dir,
                    before,
                    button_number,
                    total_elements,
                    protected_files,
                    max_wait=args.w,
                )

                elapsed = time.time() - click_start
                if status == "skipped":
                    restore_protected_files(protected_files)
                    log(f"\n[{button_number}/{total_elements}] 사용자 요청으로 건너뜁니다.")
                    skipped_count += 1
                    time.sleep(0.8)
                    continue

                if status in ("completed", "completed_without_new_file", "ui_completed"):
                    restore_protected_files(protected_files)
                    if downloaded_path:
                        run_downloaded_paths.append(downloaded_path)
                        log(f"[{button_number}/{total_elements}] 다운로드 완료! {elapsed:.3f}s - {downloaded_path.name}      ")
                    elif status == "ui_completed":
                        log(f"[{button_number}/{total_elements}] 다운로드 완료 추정 (페이지 상태 기준) {elapsed:.3f}s      ")
                    else:
                        log(f"[{button_number}/{total_elements}] 다운로드 완료! {elapsed:.3f}s      ")
                    success_count += 1
                elif status == "timeout":
                    restore_protected_files(protected_files)
                    log(f"\n[{button_number}/{total_elements}] 제한 시간({args.w}s) 초과. 다음 항목으로 이동합니다.")
                    skipped_count += 1

                time.sleep(1.0)

            except StaleElementReferenceException:
                restore_protected_files(protected_files)
                log(f"\n[{button_number}/{total_elements}] 요소가 갱신되었습니다. 같은 항목을 다시 확인합니다.")
                time.sleep(1.0)
            except Exception as e:
                restore_protected_files(protected_files)
                log(f"\n[{button_number}/{total_elements}] 에러: {e}")

    except KeyboardInterrupt:
        restore_protected_files(current_protected_files)
        log("\n\n[Ctrl+C] 사용자 중단 요청. 작업을 종료합니다.")

    total_duration = time.time() - total_start_time
    minutes, seconds = divmod(int(total_duration), 60)

    log("-" * 60)
    log(f"작업 종료. 성공: {success_count}, 건너뜀: {skipped_count} (범위 내 총 {process_count}개)")
    log(f"소요 시간: {minutes}분 {seconds}초")
    log("-" * 60)


if __name__ == "__main__":
    try:
        download_gemini_images()
    except Exception:
        setup_console()
        error_text = traceback.format_exc()
        log("치명적 오류가 발생했습니다.")
        log(error_text)
        raise
