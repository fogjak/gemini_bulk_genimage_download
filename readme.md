# 소개

**Gemini Web - Generated Image Bulk Downloader**  
by Thinking Adventure

gemini.google.com에서 한 대화에서 생성된 이미지를 다운로드받는데 한평생 걸린다면, 이 자동화 스크립트로 한 번에 자동으로 다운로드해 보세요!

---

# 필요 사항

## Python 설치

Python이 설치되어 있지 않다면, 먼저 Python을 설치해 주세요.

### Windows에서 Python 설치하기:

1. [Python 공식 웹사이트](https://www.python.org/downloads/)에 접속
2. 최신 버전 또는 **Python 3.12** 이상 다운로드
3. 설치 시 **"Add Python to PATH"** 체크박스 반드시 선택
4. 설치 완료 후 CMD 또는 PowerShell에서 확인:
   ```bash
   python --version
   ```

## Selenium 설치

터미널(CMD 또는 PowerShell)에서 아래 명령어를 실행하세요:

```bash
pip install selenium
```

이게 전부입니다!

---

# 사용 방법

## 1단계: Chrome을 원격 디버그 모드로 실행

먼저 Chrome을 디버그 모드로 실행해 주세요.

### PowerShell에서 실행:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chrometemp"
```

### 옵션 설명:
- `--remote-debugging-port=9222`: 원격 디버그 포트 지정 (기본값: 9222)
- `--user-data-dir="C:\chrometemp"`: 임시 사용자 데이터 디렉토리 (기존 프로필과 분리)

원격 디버그 포트가 열려 있어야 스크립트가 브라우저에 연결할 수 있습니다.

---

## 2단계: Gemini 웹 페이지 열기

디버그 모드로 실행된 Chrome에서 [gemini.google.com](https://gemini.google.com)으로 이동한 후, 다운로드하고 싶은 이미지가 있는 대화 페이지를 여세요.

주의. 여러 탭을 실행중인 경우 의도치 않은 탭에서 작업이 실행될 수 있습니다. 가급적 한 개의 탭으로 띄워 사용해 주세요.
팁. 원래 브라우저에서 URL을 복사해서 디버그 Chrome에 붙여넣어도 원래의 대화 내용이 

---

## 3단계: 스크립트 실행

프로젝트 폴더에서 아래 명령어를 실행하세요:

```bash
python autodown.py
```

### 옵션 사용 예시:

- **3번째 이미지부터 다운로드**:
  ```bash
  python autodown_anti.py -c 3
  ```

- **2번째부터 5개만 다운로드** (2, 3, 4, 5, 6번째):
  ```bash
  python autodown_anti.py -c 2 -l 5
  ```

### 사용 가능한 옵션:
- `-c <숫자>`: 시작 번호 (1부터 시작, 기본값: 1)
- `-l <숫자>`: 다운로드 개수 제한 (0 = 전체, 기본값: 0)

### 키보드 단축키:
- `Ctrl+C`: 프로그램 즉시 종료
- `Ctrl+N`: 현재 다운로드 건너뛰고 다음으로 이동

---

# 디버그 포트 변경하기

기본 포트(9222) 대신 다른 포트를 사용하려면, `config.conf` 파일을 편집하세요.

### config.conf 파일 수정:

메모장이나 Visual Studio Code로 `config.conf`를 열어주세요:

```ini
[options]
debugging-port=9222
```

포트 번호를 원하는 값으로 변경하면 됩니다. 예를 들어 9333을 사용하고 싶다면:

```ini
[options]
debugging-port=9333
```

**중요**: Chrome 실행 시 `--remote-debugging-port` 값도 동일하게 맞춰주세요!

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9333 --user-data-dir="C:\chrometemp"
```

### 설정 우선순위:
1. `config.conf` 파일에 포트가 명시되어 있으면 해당 포트 사용
2. 파일이 없거나 잘못된 경우 기본값 9222 사용

스크립트 실행 시 "브라우저 연결 성공! 디버그 포트: XXXX" 메시지로 현재 사용 중인 포트를 확인할 수 있습니다.

---

### 정보

# 다운로드 위치

다운로드된 이미지는 Chrome의 다운로드 폴더 설정값을 그대로 따릅니다.

# 문제 해결

### "오류: 디버깅 모드 크롬 연결 실패"가 뜨는 경우:
1. Chrome이 디버그 모드로 실행 중인지 확인하세요
2. `config.conf`의 포트 번호와 Chrome 실행 포트가 일치하는지 확인하세요
3. 방화벽이나 보안 프로그램이 로컬 포트를 차단하고 있지 않은지 확인하세요

### 다운로드가 시작되지 않는 경우:
1. Gemini 페이지가 제대로 로드되었는지 확인하세요
2. 다운로드 버튼이 실제로 존재하는지 확인하세요
3. Chrome에서 팝업 차단이 해제되어 있는지 확인하세요

### 다운로드나 동작이 느릴 경우:
1. 원본 파일 다운로드 명령 시 서버가 다운로드 이미지 전송을 위한 처리를 하는 데에 시간이 걸립니다. 한장에 평균 20초, 빨라도 최소 10초 정도 소요됩니다. 다른 작업을 하면서 기다리세요.
2. 웹 페이지 로드가 느린 PC에서는 동작이 전체적으로 느릴 수 있습니다. 가급적 웹 브라우징이 원활한 PC에서 사용하는 것을 권장합니다.

---

# 라이선스 & 연락처

**개발자**: Thinking Adventure

본 프로젝트는 개인 사용 목적으로 제작되었습니다. 문의 사항이 있으시면 이슈를 등록해 주세요.
