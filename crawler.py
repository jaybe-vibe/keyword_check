"""
Playwright 기반 네이버 검색 크롤러

- Chromium Headed 모드 + 시크릿(incognito) 컨텍스트
- 차단 방지: 랜덤 딜레이, 컨텍스트 로테이션, 자연스러운 스크롤
- 일시정지/재개/중지 제어
"""

import logging
import random
import time
import urllib.parse
from typing import Optional, Callable
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# User-Agent 풀 (Chrome 최신 버전들)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


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
        min_delay: float = 3.0,
        max_delay: float = 8.0,
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
            ],
        )
        self._create_new_context()
        self._stopped = False
        self._consecutive_errors = 0
        self._report("브라우저 시작됨")

    def _create_new_context(self):
        """새 시크릿 브라우저 컨텍스트 생성 (쿠키/세션 초기화)"""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass

        self._context = self._browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 900},
            user_agent=random.choice(USER_AGENTS),
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.page_load_timeout)
        self._search_count = 0
        self._report("새 브라우저 컨텍스트 생성")

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

        # 컨텍스트 로테이션 확인
        if self._search_count >= self.context_rotation_interval:
            self._report(f"{self._search_count}회 검색 후 컨텍스트 교체")
            self._create_new_context()

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
        """자연스러운 스크롤로 페이지 끝까지 이동 (lazy loading 대응)"""
        total_height = self._page.evaluate("document.body.scrollHeight")
        current_position = 0

        while current_position < total_height:
            scroll_amount = random.randint(300, 600)
            current_position += scroll_amount
            self._page.evaluate(f"window.scrollTo(0, {current_position})")
            time.sleep(random.uniform(0.3, 0.8))
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
        """차단 방지 딜레이 계산 (에스컬레이션 적용)"""
        base_delay = random.uniform(self.min_delay, self.max_delay)
        # 연속 에러가 있으면 딜레이 증가
        if self._consecutive_errors >= 2:
            base_delay = random.uniform(8.0, 15.0)
        return base_delay

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
