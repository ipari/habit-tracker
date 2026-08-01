# Habit Tracker

개인용 모바일 우선 습관 트래커입니다. 현재 환경 변수 기반 단일 계정 인증과 핵심 습관 기록 흐름까지 구현되어 있습니다.

현재 지원하는 흐름:

- 습관 생성, 조회, 수정 및 보관(이모지는 선택 사항이며 한 글자만 허용)
- 선택 이모지와 미지정 시 표시되는 기본 습관 아이콘
- 오늘, 습관, 달력, 설정을 오가는 아이콘 전용 Liquid Glass 스타일 모바일 하단 탭
- 오늘·습관·달력 목록의 연속 달성·수행 요일·12시간제 알림 시간 요약
- 오늘·달력 목록의 미달성 우선 및 알림 시간 오름차순 정렬
- 진행 중인 습관과 접을 수 있는 `지난 습관들` 영역
- 목록에서 습관 상세로 이동해 편집·공유하고, 기록을 보존한 채 삭제하는 관리 흐름
- 홈 또는 습관들 중 실제 진입 화면을 유지하는 상세·편집 뒤로가기
- 달력에서 예정 습관과 추가 달성을 구분하고 비예정 습관을 기록하는 `다른 습관 기록` 흐름
- 옅은 테두리로 오늘을 표시하고 완료·부분 달성·미달성을 날짜 아래 색상 점으로 구분하는 간결한 월간 달력
- 현지 날짜부터 적용되는 수행 요일 변경 이력
- 오늘 예정된 습관의 완료 및 완료 취소
- 예정일, 추가 달성 및 과거 누락을 반영한 현재 streak
- 월간 달력 탐색과 오늘·과거 날짜의 완료 기록 수정
- 날짜별 예정일 달성, 예정일 미달성, 추가 달성 및 미래 읽기 전용 상태
- 습관별 공유 배경 프리셋 선택
- 현재 streak를 담은 1080×1920 PNG 미리보기, 시스템 공유 및 다운로드
- 습관별 알림 활성화, 수행 요일을 따르는 반복 요일, 현지 시간 및 IANA 시간대 설정 저장
- 설정 화면에서 기기의 IANA 시간대를 자동 감지·적용하고 현재 기기 알림 연결 해제
- 설정 화면에서 시스템 설정·Light·Dark 중 화면 모드를 기기별로 선택
- 홈 화면에 설치 가능한 PWA와 정적 자산 캐시
- 연결이 끊겼을 때 표시되는 오프라인 안내 및 기록 변경 차단

수행 일정은 시작일을 포함하고 종료일은 포함하지 않는 구간으로 저장됩니다. 같은 날 여러 번 수정하면 그날의 일정 행을 교체하며, 이후 날짜에 수정하면 기존 일정은 보존됩니다.

알림 요일은 항상 습관의 수행 요일을 따라갑니다. 습관을 보관하면 해당 알림도 비활성화됩니다. 별도 스케줄러 프로세스가 현지 시간과 IANA 시간대를 기준으로 활성 기기에 Web Push를 발송하며, 만료된 구독은 자동으로 비활성화합니다.

## 로컬 실행

Python 3.12와 프로젝트 정책을 만족하는 SQLite가 필요합니다.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

8자 이상의 비밀번호를 준비합니다. 비밀번호는 명령 인자로 전달하지 않고 대화형 명령으로 Argon2id 해시를 생성합니다.

```bash
.venv/bin/python -m app.auth.hash_password
```

`.env`에 다음 값을 설정합니다. 실제 비밀번호는 저장하지 않습니다.

```dotenv
HABIT_TRACKER_USERNAME=owner
HABIT_TRACKER_PASSWORD_HASH='<위 명령이 출력한 Argon2id 해시>'
SESSION_SECRET=<32자 이상의 무작위 비밀 키>
SESSION_COOKIE_SECURE=false
DATABASE_URL=sqlite:///./data/habit_tracker.db
```

Web Push용 VAPID 키는 최초 한 번만 생성하고 계속 보관합니다.

```bash
.venv/bin/python -m app.push.generate_vapid_keys
```

출력된 두 값과 발송자를 식별할 `mailto:` 주소 또는 HTTPS URL을 `.env`에 추가합니다.

```dotenv
VAPID_PUBLIC_KEY=<생성된 공개 키>
VAPID_PRIVATE_KEY=<생성된 개인 키>
VAPID_SUBJECT=mailto:owner@example.com
REMINDER_POLL_SECONDS=30
REMINDER_LOOKBACK_MINUTES=5
```

`VAPID_PRIVATE_KEY`는 비밀번호와 같은 비밀 값이므로 저장소에 커밋하지 않습니다. VAPID 키를 교체하면 기존 브라우저 구독도 새 공개 키로 다시 연결되어야 합니다.

Argon2id 해시의 `$` 문자가 Compose 환경 변수 치환으로 해석되지 않도록 해시 전체를 작은따옴표로 감쌉니다.

운영 `.env`는 파일 권한을 `600`으로 설정합니다. 비밀번호를 변경하려면 새 해시를 생성해 `HABIT_TRACKER_PASSWORD_HASH`를 교체하고 앱을 재시작합니다. 기존 로그인 세션은 새 해시와 일치하지 않아 자동으로 무효화됩니다.

```bash
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

개발 중 실제 예약 발송을 확인하려면 다른 터미널에서 스케줄러를 실행합니다.

```bash
.venv/bin/python -m app.reminders.scheduler
```

## 앱 설치와 오프라인 동작

로컬에서는 `http://127.0.0.1:8000`에 접속해 브라우저의 앱 설치 또는 홈 화면 추가 기능을 사용할 수 있습니다. 운영 환경의 PWA와 Web Push 기능에는 HTTPS가 필요합니다.

서비스 워커는 CSS, JavaScript, 앱 아이콘만 캐시합니다. 습관 데이터와 HTML 응답은 캐시하지 않으며, 네트워크 연결이 끊기면 상단에 안내를 표시하고 완료 체크·수정·로그아웃 같은 쓰기 요청을 보내지 않습니다. 연결이 복구되면 현재 페이지에서 다시 시도할 수 있습니다.

앱을 설치하면 설치 직후 또는 홈 화면 앱의 첫 실행에 알림 안내가 표시됩니다. 브라우저 정책에 맞춰 시스템 권한 창은 사용자가 `알림 허용` 버튼을 누른 경우에만 열립니다. 허용 후에는 해당 기기의 Push Subscription을 서버에 저장합니다. 이전 버전에서 권한만 허용한 기기에는 `기기 연결` 안내가 다시 표시됩니다. 거부하거나 지원되지 않는 환경에는 기기 설정 안내가 표시됩니다.

설정 화면을 열면 브라우저가 기기의 IANA 시간대를 감지해 서버 설정과 기존 습관 알림에 자동으로 적용합니다. 기존 알림의 현지 시각은 그대로 유지합니다. `연결 해제`는 현재 기기의 Push Subscription만 비활성화하며 브라우저 자체의 알림 권한은 변경하지 않습니다.

오늘 또는 습관 목록에서 습관 상세 화면을 연 뒤 `공유`를 누르면 선택한 배경 프리셋, 현재 streak, 습관 시작일로 1080×1920 이미지를 만듭니다. 상세 화면에는 첫 시작일, 요일, 저장된 시간, 알림 켜짐 여부를 표시합니다. `삭제`는 과거 달성 기록과 일정을 지우지 않고 습관을 보관합니다. 브라우저가 파일 공유를 지원하면 시스템 공유 시트를 열고, 지원하지 않거나 공유에 실패하면 PNG 다운로드를 사용할 수 있습니다. 이미지에는 로그인 아이디나 서비스 주소를 넣지 않습니다.

앱 아이콘을 변경한 뒤 PNG 파일을 다시 만들려면 다음 명령을 실행합니다.

```bash
.venv/bin/python scripts/generate_app_icons.py
```

## 검사

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy app tests
```

## Docker Compose

운영 환경에서는 `SESSION_COOKIE_SECURE=true`를 사용하고 HTTPS 리버스 프록시 뒤에서 실행합니다. 기본 호스트 바인딩은 `127.0.0.1:8000`이므로 외부 인터페이스에 직접 공개되지 않습니다. 포트가 이미 사용 중이면 `.env`의 `HABIT_TRACKER_PORT`를 변경할 수 있습니다.

```bash
docker compose build
docker compose up -d
```

DB는 로컬 실행용 `.env`의 상대 경로와 관계없이 `habit_data` named volume의 `/data/habit_tracker.db`에 저장됩니다. API와 단일 스케줄러 컨테이너가 같은 volume을 사용하며 스케줄러는 API health check와 마이그레이션 완료 후 시작합니다. SQLite 버전은 이미지 빌드, 마이그레이션 및 애플리케이션 시작 시 검사됩니다. 인증 자격 증명과 VAPID 개인 키는 DB나 Docker 이미지에 저장되지 않습니다.
