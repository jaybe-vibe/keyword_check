"""
Playwright 기반 네이버 검색 크롤러

- Chromium Headed 모드 + 시크릿(incognito) 컨텍스트
- 차단 방지: 랜덤 딜레이, 컨텍스트 로테이션, 자연스러운 스크롤
- 안티봇 방어: fingerprint 제거, HTTP 헤더 위장, 워밍업 세션
- 일시정지/재개/중지 제어
"""

import logging
import math
import random
import time
import urllib.parse
from typing import Optional, Callable
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# User-Agent 풀 (Chrome 133~135, Windows 70% / Mac 30% 비율 반영)
USER_AGENTS = [
    # Windows - Chrome 135
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    # Windows - Chrome 134
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.89 Safari/537.36",
    # Windows - Chrome 133
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.127 Safari/537.36",
    # Windows 11 variants
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0",
    # Mac - Chrome 135
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    # Mac - Chrome 134
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Mac - Chrome 133
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
]

# Viewport 풀 (일반적인 해상도)
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1280, "height": 720},
]

# Playwright 자동화 지문 제거 스크립트
STEALTH_SCRIPT = """
// navigator.webdriver 제거
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// chrome 객체 위장
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' } },
};

// plugins 위장 (빈 배열이면 headless 탐지됨)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
        plugins.length = 3;
        return plugins;
    },
});

// languages 위장
Object.defineProperty(navigator, 'languages', {
    get: () => ['ko-KR', 'ko', 'en-US', 'en'],
});

// permissions.query 위장
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);

// WebGL renderer 위장
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(param) {
    if (param === 37445) return 'Intel Inc.';
    if (param === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, param);
};
"""


class NaverCrawler:
    """
    Playwright 기반 네이버 검색 크롤러.

    사용법:
        crawler = NaverCrawler(headed=True)
        crawler.start()
        result = crawler.search("임산부 효소")
        crawler.stop()
    """

    def __init__(
        self,
        headed: bool = True,
        min_delay: float = 5.0,
        max_delay: float = 12.0,
        context_rotation_interval: int = 12,
        page_load_timeout: int = 15000,
        scroll_delay: float = 1.5,
        on_status: Optional[Callable] = None,
    ):
        self.headed = headed
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.context_rotation_interval = context_rotation_interval
        self.page_load_timeout = page_load_timeout
        self.scroll_delay = scroll_delay
        self.on_status = on_status

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._search_count = 0
        self._rotation_target = 0  # 랜덤화된 로테이션 목표
        self._paused = False
        self._stopped = False
        self._consecutive_errors = 0

    def start(self):
        """브라우저 실행 및 초기 컨텍스트 생성"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=not self.headed,
            args=[
                "--lang=ko-KR",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        self._create_new_context()
        self._stopped = False
        self._consecutive_errors = 0
        self._report("브라우저 시작됨")

    def _create_new_context(self):
        """새 시크릿 브라우저 컨텍스트 생성 (쿠키/세션 초기화, fingerprint 위장)"""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass

        ua = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORTS)

        # UA에서 Chrome 주 버전 추출
        chrome_ver = "135"
        if "Chrome/" in ua:
            chrome_ver = ua.split("Chrome/")[1].split(".")[0]

        self._context = self._browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport=viewport,
            user_agent=ua,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "sec-ch-ua": f'"Chromium";v="{chrome_ver}", "Google Chrome";v="{chrome_ver}", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        self._page = self._context.new_page()
        self._page.add_init_script(STEALTH_SCRIPT)
        self._page.set_default_timeout(self.page_load_timeout)
        self._search_count = 0
        self._rotation_target = self.context_rotation_interval + random.randint(-3, 3)
        self._report(f"새 브라우저 컨텍스트 생성 (viewport {viewport['width']}x{viewport['height']}, 로테이션 {self._rotation_target}회)")

    def _warm_up_session(self):
        """네이버 메인 방문으로 쿠키 획득 및 Referer 자연화"""
        try:
            self._page.goto("https://www.naver.com", wait_until="domcontentloaded")
            time.sleep(random.uniform(1.0, 2.5))
            self._report("네이버 메인 워밍업 완료")
        except Exception as e:
            self._report(f"워밍업 실패 (무시): {e}")

    def search(self, keyword: str) -> dict:
        """
        키워드를 네이버에서 검색하고 HTML 반환.

        Returns:
            {
                "keyword": str,
                "html": str,
                "url": str,
                "success": bool,
                "error": str,
                "blocked": bool,
            }
        """
        if self._stopped:
            return self._error_result(keyword, "크롤러가 중지됨")

        # 일시정지 대기
        while self._paused:
            time.sleep(0.5)
            if self._stopped:
                return self._error_result(keyword, "크롤러가 중지됨")

        # 컨텍스트 로테이션 확인 (랜덤화된 간격)
        if self._search_count >= self._rotation_target:
            self._report(f"{self._search_count}회 검색 후 컨텍스트 교체")
            self._create_new_context()

        # 새 컨텍스트 첫 검색 시 네이버 메인 워밍업
        if self._search_count == 0:
            self._warm_up_session()
        # 가끔 메인 경유 (7% 확률) - 자연스러운 네비게이션 패턴
        elif random.random() < 0.07:
            self._warm_up_session()

        # 검색 간 딜레이 (첫 검색 제외)
        if self._search_count > 0:
            delay = self._get_delay()
            self._report(f"{delay:.1f}초 대기 중...")
            time.sleep(delay)

        try:
            # 네이버 검색 페이지 이동
            encoded = urllib.parse.quote(keyword)
            search_url = f"https://search.naver.com/search.naver?query={encoded}"
            self._page.goto(search_url, wait_until="domcontentloaded")

            # 메인 콘텐츠 로딩 대기
            try:
                self._page.wait_for_selector(
                    "div#main_pack", timeout=10000
                )
            except Exception:
                pass  # main_pack이 없을 수도 있음, 계속 진행

            # 페이지 스크롤 (모든 스마트블록 로딩)
            self._scroll_page()

            # 차단 감지
            if self._detect_blocking():
                self._consecutive_errors += 1
                self._handle_blocking_escalation()
                return {
                    "keyword": keyword,
                    "html": "",
                    "url": self._page.url,
                    "success": False,
                    "error": "차단 감지 (CAPTCHA 또는 속도 제한)",
                    "blocked": True,
                }

            # HTML 추출
            html = self._page.content()
            self._search_count += 1
            self._consecutive_errors = 0
            self._report(f"'{keyword}' 검색 완료")

            return {
                "keyword": keyword,
                "html": html,
                "url": self._page.url,
                "success": True,
                "error": "",
                "blocked": False,
            }

        except Exception as e:
            self._consecutive_errors += 1
            error_msg = str(e)
            self._report(f"'{keyword}' 검색 오류: {error_msg}")

            # 연속 에러 시 컨텍스트 교체
            if self._consecutive_errors >= 3:
                self._report("연속 에러 감지, 컨텍스트 교체")
                self._create_new_context()
                self._consecutive_errors = 0

            return self._error_result(keyword, error_msg)

    def _scroll_page(self):
        """사람처럼 비균일 스크롤 (가변 속도 + 읽기 멈춤)"""
        total_height = self._page.evaluate("document.body.scrollHeight")
        current_position = 0

        while current_position < total_height:
            # 스크롤 양도 가변적 (200~500px 로그정규분포)
            scroll_amount = int(random.lognormvariate(math.log(350), 0.25))
            scroll_amount = max(200, min(scroll_amount, 600))
            current_position += scroll_amount
            self._page.evaluate(f"window.scrollTo(0, {current_position})")

            # 가끔 멈춰서 읽는 것처럼 (15% 확률)
            if random.random() < 0.15:
                time.sleep(random.uniform(1.0, 2.5))
            else:
                time.sleep(random.uniform(0.2, 0.6))

            total_height = self._page.evaluate("document.body.scrollHeight")

        # 최종 대기 (렌더링 완료)
        time.sleep(self.scroll_delay)

    def _detect_blocking(self) -> bool:
        """CAPTCHA/차단 페이지 감지"""
        try:
            page_text = self._page.inner_text("body")
            blocking_signals = [
                "자동 입력 방지",
                "비정상적인 접근",
                "잠시 후 다시",
                "보안 문자",
                "captcha",
                "unusual traffic",
            ]
            page_lower = page_text.lower()
            return any(signal.lower() in page_lower for signal in blocking_signals)
        except Exception:
            return False

    def _get_delay(self) -> float:
        """로그정규분포 딜레이 (사람 행동 패턴 모사, 에스컬레이션 적용)"""
        if self._consecutive_errors >= 2:
            return random.uniform(10.0, 20.0)

        # 로그정규분포: 중앙값 ~7초, 대부분 5~12초, 간헐적 15초+
        mu = math.log((self.min_delay + self.max_delay) / 2)
        delay = random.lognormvariate(mu, 0.3)
        return max(self.min_delay, min(delay, self.max_delay * 1.5))

    def _handle_blocking_escalation(self):
        """차단 감지 시 에스컬레이션 처리"""
        if self._consecutive_errors >= 2:
            self._report("2회 이상 차단 감지 - 크롤링 일시정지")
            self._paused = True
        else:
            wait_time = 60
            self._report(f"차단 감지 - {wait_time}초 대기 후 컨텍스트 교체")
            time.sleep(wait_time)
            self._create_new_context()

    def pause(self):
        """크롤링 일시정지"""
        self._paused = True
        self._report("크롤러 일시정지")

    def resume(self):
        """크롤링 재개"""
        self._paused = False
        self._consecutive_errors = 0
        self._report("크롤러 재개")

    def stop(self):
        """크롤러 종료 및 브라우저 닫기"""
        self._stopped = True
        self._paused = False
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning("크롤러 종료 중 오류: %s", e)
        self._report("크롤러 종료")

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_stopped(self) -> bool:
        return self._stopped

    def _report(self, message: str):
        """상태 콜백 호출"""
        if self.on_status:
            self.on_status(message)

    def _error_result(self, keyword: str, error: str) -> dict:
        return {
            "keyword": keyword,
            "html": "",
            "url": "",
            "success": False,
            "error": error,
            "blocked": False,
        }
