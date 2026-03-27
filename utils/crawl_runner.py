"""크롤링 백그라운드 스레드 함수 (app.py에서 분리)"""

import sys
import asyncio
import time
import random
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

# 배치 크롤링 설정 (안티봇 최적화)
BATCH_SIZE_MIN = 25    # 배치 크기 최소
BATCH_SIZE_MAX = 35    # 배치 크기 최대 (랜덤화)
BATCH_REST_MIN = 300   # 배치 간 최소 휴식 (초) = 5분
BATCH_REST_MAX = 600   # 배치 간 최대 휴식 (초) = 10분


def run_crawl_thread(keywords: list[str], crawler_config: dict,
                     shared: dict, results_dict: dict):
    """백그라운드에서 크롤링 실행 (threading.Thread 대상).

    50개 이상 키워드는 배치로 나눠 처리하며 배치 간 2~3분 휴식.
    크롤링 완료 시 Excel 자동 내보내기.

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
        min_delay=crawler_config.get("min_delay", 5.0),
        max_delay=crawler_config.get("max_delay", 12.0),
        context_rotation_interval=crawler_config.get("context_rotation_interval", 12),
        on_status=on_status,
    )
    parser = NaverSearchParser(debug=True)

    total = len(keywords)
    # 배치 크기 랜덤화 (25~35개)
    batch_size = random.randint(BATCH_SIZE_MIN, BATCH_SIZE_MAX)
    batches = [keywords[i:i + batch_size] for i in range(0, total, batch_size)]
    total_batches = len(batches)
    stopped = False

    try:
        crawler.start()

        if total_batches > 1:
            on_status(f"키워드 {total}개 → {batch_size}개씩 {total_batches}배치로 나눠 크롤링합니다.")

        global_idx = 0  # 전체 키워드 기준 인덱스

        for batch_num, batch in enumerate(batches, 1):
            if shared["stop_signal"]:
                stopped = True
                on_status("크롤링 중지됨 (사용자 요청)")
                break

            if total_batches > 1:
                on_status(f"── 배치 {batch_num}/{total_batches} 시작 ({len(batch)}개 키워드) ──")

            for keyword in batch:
                if shared["stop_signal"]:
                    stopped = True
                    on_status("크롤링 중지됨 (사용자 요청)")
                    break

                while shared["pause_signal"]:
                    time.sleep(0.5)
                    if shared["stop_signal"]:
                        break

                if shared["stop_signal"]:
                    stopped = True
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

                global_idx += 1
                shared["completed"] = global_idx
                shared["progress"] = global_idx / total

            if stopped:
                break

            # 배치 간 휴식 (마지막 배치 제외)
            if total_batches > 1 and batch_num < total_batches:
                rest_sec = random.randint(BATCH_REST_MIN, BATCH_REST_MAX)
                on_status(f"── 배치 {batch_num}/{total_batches} 완료. {rest_sec}초({rest_sec // 60}분 {rest_sec % 60}초) 휴식 ──")
                # 휴식 중에도 중지/일시정지 신호 확인
                for _ in range(rest_sec):
                    if shared["stop_signal"]:
                        stopped = True
                        on_status("휴식 중 크롤링 중지됨 (사용자 요청)")
                        break
                    time.sleep(1)
                if stopped:
                    break
                on_status(f"── 휴식 완료. 배치 {batch_num + 1}/{total_batches} 시작 준비 ──")

    except Exception as e:
        tb = traceback.format_exc()
        on_status(f"크롤링 오류: {type(e).__name__}: {e}")
        logger.error("크롤링 오류: %s\n%s", e, tb)
        shared["status"] = "error"
    finally:
        crawler.stop()
        if shared["status"] != "error" and not shared["stop_signal"]:
            shared["status"] = "completed"
            # 크롤링 정상 완료 시 Excel 자동 내보내기
            _auto_export(results_dict, on_status)
        shared["current"] = ""


def _auto_export(results_dict: dict, on_status):
    """크롤링 완료 후 Excel 자동 내보내기"""
    try:
        from pages.export import auto_export_excel
        on_status("Excel 자동 내보내기 시작...")
        output_path = auto_export_excel(results_dict)
        on_status(f"Excel 저장 완료: {output_path}")
    except Exception as e:
        logger.error("Excel 자동 내보내기 실패: %s", e)
        on_status(f"Excel 자동 내보내기 실패: {e}")


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
