import os
import time
import argparse
import msvcrt
import sys
import configparser
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

def load_config():
    """config.conf 파일에서 디버깅 포트를 읽어옵니다. 파일이 없거나 오류가 있으면 기본값 9222를 반환합니다."""
    config = configparser.ConfigParser()
    default_port = 9222
    
    try:
        config.read('config.conf', encoding='utf-8')
        if 'options' in config and 'debugging-port' in config['options']:
            port = int(config['options']['debugging-port'])
            return port
        else:
            return default_port
    except Exception:
        return default_port

def download_gemini_images():
    # ---------------------------------------------------------
    # 0. 매개변수 파싱
    # ---------------------------------------------------------
    parser = argparse.ArgumentParser(description="Gemini Image Auto Downloader")
    parser.add_argument("-c", type=int, default=1, help="Start from Nth image (1-based index)")
    parser.add_argument("-l", type=int, default=0, help="Limit number of downloads (0 for all)")
    args = parser.parse_args()

    start_index = args.c - 1
    if start_index < 0:
        print("오류: 시작 인덱스(-c)는 1 이상이어야 합니다.")
        return

    limit_count = args.l
    if limit_count < 0:
        print("오류: 개수 제한(-l)은 0 이상이어야 합니다.")
        return

    # ---------------------------------------------------------
    # 1. 설정 및 연결
    # ---------------------------------------------------------
    download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    
    # config.conf에서 디버깅 포트 읽기
    debug_port = load_config()
    
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")

    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        print(f"오류: 디버깅 모드 크롬 연결 실패. (포트: {debug_port})")
        print("Chrome을 디버그 모드로 실행했는지 확인하세요.")
        return

    # CDP 권한 재설정 (다운로드 차단 방지)
    params = {"behavior": "allow", "downloadPath": download_dir}
    driver.execute_cdp_cmd("Page.setDownloadBehavior", params)

    print(f"📂 저장 경로: {download_dir}")
    print(f"브라우저 연결 성공! 디버그 포트: {debug_port}")
    print("💡 사용법: [Ctrl+C] 종료 | [Ctrl+N] 현재 항목 건너뛰기")

    # ---------------------------------------------------------
    # 2. 버튼 찾기 (Stale Element 방지 로직 포함)
    # ---------------------------------------------------------
    selector = 'button[aria-label="원본 크기 이미지 다운로드"]'
    buttons = driver.find_elements(By.CSS_SELECTOR, selector)
    
    if not buttons:
        print("다운로드 버튼을 찾을 수 없습니다.")
        return

    total_elements = len(buttons)
    
    # 다운로드 범위 계산
    end_index = total_elements
    if limit_count > 0:
        end_index = min(start_index + limit_count, total_elements)
    
    # 범위 유효성 검사
    if start_index >= total_elements:
        print(f"오류: 시작 번호({args.c})가 총 이미지 수({total_elements})보다 큽니다.")
        return

    process_count = end_index - start_index
    print(f"총 {total_elements}개의 이미지 요소 발견.")
    if limit_count > 0:
         print(f"🎯 {args.c}번째부터 {process_count}개만 다운로드합니다. (범위: {args.c}~{end_index})")
    else:
         print(f"🎯 {args.c}번째부터 끝까지 다운로드합니다.")
    print("-" * 50)

    total_start_time = time.time()
    success_count = 0
    skipped_count = 0
    
    try:
        # 실제 루프는 전체 range를 돌되, index로 필터링
        # (Stale 방지를 위해 전체 리스트에서의 인덱스가 중요함)
        for i in range(start_index, end_index):
            try:
                # Key Check: 시작 전
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key == b'\x03': # Ctrl+C (Standard interrupt code, though usually caught by exception)
                        raise KeyboardInterrupt

                # DOM 요소가 변경되었을 수 있으므로 매번 다시 찾기 (가장 안전함)
                current_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                if i >= len(current_buttons):
                    print(f"[{i+1}] 버튼을 찾을 수 없습니다. (리스트 변경됨)")
                    break
                
                btn = current_buttons[i]
                
                # [핵심 1] 화면에 안 보이는 버튼 강제 호출 (스크롤)
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});", btn)
                time.sleep(1.0) # 스크롤 후 렌더링 대기
                
                # 클릭 시도
                click_start = time.time()
                driver.execute_script("arguments[0].click();", btn)
                print(f"[{i+1}/{total_elements}] 다운로드 요청 완료. 상태 확인 중...", end="\r")

                # 스피너 대기
                time.sleep(2.0)

                # [핵심 3] 다운로드 완료 대기 (스피너 감지) + 키보드 제어
                wait_start = time.time()
                max_wait = 60
                is_spinning = False
                force_skip = False

                while time.time() - wait_start < max_wait:
                    # 키 입력 감지 (Wait Loop 내부)
                    if msvcrt.kbhit():
                        key = msvcrt.getch()
                        if key == b'\x0e': # Ctrl+N
                            print(f"\n[{i+1}/{total_elements}] ⏭️ 사용자 요청으로 건너뜁니다.")
                            force_skip = True
                            skipped_count += 1
                            break
                        # Ctrl+C는 외부 try-except로 전파되거나 여기서 처리
                        # msvcrt에서 Ctrl+C는 보통 KeyboardInterrupt를 일으키지 않고 \x03을 반환함
                        if key == b'\x03': 
                             raise KeyboardInterrupt

                    try:
                        current_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                        if i >= len(current_buttons): break
                        
                        target_btn = current_buttons[i]
                        spinners = target_btn.find_elements(By.CSS_SELECTOR, "mat-spinner")
                        
                        if spinners:
                            if not is_spinning:
                                print(f"[{i+1}/{total_elements}] 다운로드 진행 중... (스피너 감지)     ", end="\r")
                                is_spinning = True
                            time.sleep(0.5) # 반응성을 위해 대기 시간 줄임
                        else:
                            elapsed = time.time() - click_start
                            if is_spinning:
                                print(f"[{i+1}/{total_elements}] 다운로드 완료! {elapsed:.3f}s      ")
                            else:
                                print(f"[{i+1}/{total_elements}] 다운로드 완료 추정 (스피너 없음) {elapsed:.3f}s      ")
                            break
                            
                    except Exception:
                        time.sleep(1)
                
                if force_skip:
                    time.sleep(1.0) # 건너뛰기 후 잠시 대기
                    continue # 다음 루프로

                # 다운로드 완료 후 대기
                time.sleep(2.0)
                success_count += 1
                    
            except StaleElementReferenceException:
                print(f"\n[{i+1}/{total_elements}] 요소가 만료됨. 재시도합니다.")
                time.sleep(1)
            except Exception as e:
                print(f"\n[{i+1}/{total_elements}] 에러: {e}")

    except KeyboardInterrupt:
        print("\n\n🛑 [Ctrl+C] 사용자 중단 요청. 작업을 종료합니다.")
    
    # 최종 리포트
    total_duration = time.time() - total_start_time
    m, s = divmod(int(total_duration), 60)

    print("-" * 60)
    print(f"작업 종료. 성공: {success_count}, 건너뜀: {skipped_count} (범위 내 총 {process_count}개)")
    print(f"소요 시간: {m}분 {s}초")
    print("-" * 60)

if __name__ == "__main__":
    download_gemini_images()