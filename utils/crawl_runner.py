"""크롤링 백그라운드 스레드 함수 (app.py에서 분리)"""

import sys
import asyncio
import time
import logging
import traceback
from datetime import datetime
from pathlib import Path

from crawler import NaverCrawler
from parser import NaverSearchParser
from models import KeywordResult
from utils.keyword_utils import sanitize_filename

logger = logging.getLogger(__name__)

# 디버그 HTML 최대 보관 파일 수
MAX_DEBUG_HTML_FILES = 100


def run_crawl_thread(keywords: list[str], crawler_config: dict,
                     shared: dict, results_dict: dict):
    """백그라운드에서 크롤링 실행 (threading.Thread 대상).

    Args:
        shared: 스레드↔메인 통신용 일반 dict (st.session_state 대신)
        results_dict: 키워드별 결과를 저장할 dict 참조
    """
    # Windows: Playwright는 ProactorEventLoop이 필요
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    def on_status(msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        shared["log"].append(f"[{timestamp}] {msg}")

    crawler = NaverCrawler(
        headed=crawler_config.get("headed", True),
        min_delay=crawler_config.get("min_delay", 3.0),
        max_delay=crawler_config.get("max_delay", 8.0),
        context_rotation_interval=crawler_config.get("context_rotation_interval", 12),
        on_status=on_status,
    )
    parser = NaverSearchParser(debug=True)

    try:
        crawler.start()

        for i, keyword in enumerate(keywords):
            if shared["stop_signal"]:
                on_status("크롤링 중지됨 (사용자 요청)")
                break

            while shared["pause_signal"]:
                time.sleep(0.5)
                if shared["stop_signal"]:
                    break

            if shared["stop_signal"]:
                break

            shared["current"] = keyword
            on_status(f"'{keyword}' 검색 시작")

            raw = crawler.search(keyword)

            if keyword not in results_dict:
                results_dict[keyword] = KeywordResult(keyword=keyword)

            result = results_dict[keyword]

            if raw["success"]:
                _save_debug_html(keyword, raw["html"], on_status)

                parsed = parser.parse(raw["html"])
                result.smart_blocks = parsed["blocks"]
                result.related_keywords = parsed["related_keywords"]
                result.crawled_at = datetime.now()
                result.error = ""

                block_names = [b.block_name for b in parsed["blocks"]]
                on_status(f"'{keyword}' 완료: 블록 {len(block_names)}개 [{', '.join(block_names)}]")

                if parsed.get("debug_log"):
                    for log_line in parsed["debug_log"]:
                        on_status(f"  [파서] {log_line}")
            else:
                result.error = raw["error"]
                result.crawled_at = datetime.now()
                on_status(f"'{keyword}' 오류: {raw['error']}")

                if raw.get("blocked"):
                    shared["pause_signal"] = True
                    shared["status"] = "paused"
                    on_status("차단 감지 - 크롤링 일시정지됨. 재개 버튼을 눌러주세요.")

            shared["completed"] = i + 1
            shared["progress"] = (i + 1) / len(keywords)

    except Exception as e:
        tb = traceback.format_exc()
        on_status(f"크롤링 오류: {type(e).__name__}: {e}")
        logger.error("크롤링 오류: %s\n%s", e, tb)
        shared["status"] = "error"
    finally:
        crawler.stop()
        if shared["status"] != "error" and not shared["stop_signal"]:
            shared["status"] = "completed"
        shared["current"] = ""


def _save_debug_html(keyword: str, html: str, on_status):
    """디버그 HTML 저장 (파일 수 제한 적용)"""
    try:
        debug_dir = Path("data/debug_html")
        debug_dir.mkdir(parents=True, exist_ok=True)

        # 오래된 파일 정리
        existing = sorted(debug_dir.glob("*.html"), key=lambda p: p.stat().st_mtime)
        while len(existing) >= MAX_DEBUG_HTML_FILES:
            existing[0].unlink()
            existing.pop(0)

        safe_name = sanitize_filename(keyword)
        with open(debug_dir / f"{safe_name}.html", "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        logger.warning("디버그 HTML 저장 실패: %s", e)
