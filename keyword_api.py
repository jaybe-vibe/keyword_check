"""
네이버 검색광고 API 클라이언트 - 키워드 검색량 조회

API 문서: https://github.com/naver/searchad-apidoc
엔드포인트: GET https://api.searchad.naver.com/keywordstool
인증: HMAC-SHA256 서명
"""

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)

BASE_URL = "https://api.searchad.naver.com"


def _safe_float(value) -> float:
    """API 응답값을 안전하게 float로 변환 (문자열 '< 10' 등 대응)"""
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _safe_int(value) -> int:
    """API 응답값을 안전하게 int로 변환 ('< 10' → 5)"""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return 5
    return int(value) if isinstance(value, float) else 0


def _parse_keyword_item(item: dict) -> dict:
    """API 응답 아이템을 공통 포맷으로 파싱"""
    pc = _safe_int(item.get("monthlyPcQcCnt", 0))
    mobile = _safe_int(item.get("monthlyMobileQcCnt", 0))
    return {
        "pc": pc,
        "mobile": mobile,
        "total": pc + mobile,
        "competition": item.get("compIdx", ""),
        "avg_pc_clicks": _safe_float(item.get("monthlyAvePcClkCnt", 0)),
        "avg_mobile_clicks": _safe_float(item.get("monthlyAveMobileClkCnt", 0)),
        "avg_pc_ctr": _safe_float(item.get("monthlyAvePcCtr", 0)),
        "avg_mobile_ctr": _safe_float(item.get("monthlyAveMobileCtr", 0)),
        "avg_ad_count": _safe_float(item.get("plAvgDepth", 0)),
    }


class NaverAdsAPIClient:
    """네이버 검색광고 API 클라이언트"""

    def __init__(self, customer_id: str, api_key: str, secret_key: str):
        self.customer_id = customer_id
        self.api_key = api_key
        self.secret_key = secret_key
        self._session = self._create_session()

    def _create_session(self) -> requests.Session:
        """재시도 로직이 포함된 requests 세션 생성"""
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=1.0, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        return session

    def _generate_signature(self, timestamp: str, method: str, uri: str) -> str:
        """HMAC-SHA256 서명 생성"""
        sign_str = f"{timestamp}.{method}.{uri}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def _get_headers(self, method: str, uri: str) -> dict:
        """인증 헤더 생성"""
        timestamp = str(round(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, uri)
        return {
            "X-API-KEY": self.api_key,
            "X-CUSTOMER": self.customer_id,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
        }

    def get_keyword_volumes(self, keywords: list[str], show_detail: int = 1) -> list[dict]:
        """키워드 검색량 조회."""
        uri = "/keywordstool"
        method = "GET"
        headers = self._get_headers(method, uri)

        cleaned = [kw.replace(" ", "") for kw in keywords]
        encoded_keywords = ",".join(urllib.parse.quote(kw) for kw in cleaned)
        url = f"{BASE_URL}{uri}?hintKeywords={encoded_keywords}&showDetail={show_detail}"

        response = self._session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("keywordList", [])

    def get_volumes_batched(
        self,
        keywords: list[str],
        batch_size: int = 5,
        delay: float = 0.5,
    ) -> dict:
        """배치 단위로 검색량 조회."""
        results = {}

        stripped_to_original = {}
        for kw in keywords:
            stripped_to_original[kw.replace(" ", "")] = kw

        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            try:
                api_results = self.get_keyword_volumes(batch)
                for item in api_results:
                    rel_kw = item.get("relKeyword", "")
                    vol_data = _parse_keyword_item(item)

                    original_kw = stripped_to_original.get(rel_kw.replace(" ", ""), rel_kw)
                    results[original_kw] = vol_data

                    if rel_kw != original_kw:
                        results[rel_kw] = vol_data

            except Exception as e:
                logger.warning("배치 %d 검색량 조회 실패: %s", i // batch_size + 1, e)
                for kw in batch:
                    if kw not in results:
                        results[kw] = {
                            "pc": 0, "mobile": 0, "total": 0,
                            "competition": "",
                            "error": "조회 실패",
                        }

            if i + batch_size < len(keywords):
                time.sleep(delay)

        return results

    def get_related_keywords(self, keyword: str) -> list[dict]:
        """키워드의 연관키워드 목록 조회 (검색량 포함)."""
        try:
            api_results = self.get_keyword_volumes([keyword])
        except Exception as e:
            logger.warning("연관키워드 조회 실패 (%s): %s", keyword, e)
            return []

        cleaned_kw = keyword.replace(" ", "")
        related = []
        for item in api_results:
            rel_kw = item.get("relKeyword", "")
            if rel_kw.replace(" ", "") == cleaned_kw:
                continue
            vol_data = _parse_keyword_item(item)
            vol_data["keyword"] = rel_kw
            related.append(vol_data)

        return related

    def get_related_keywords_batch(
        self,
        keywords: list[str],
        batch_size: int = 5,
        delay: float = 0.5,
    ) -> dict:
        """여러 키워드의 연관키워드를 배치로 조회.

        Returns:
            {keyword: [related_kw_dict, ...]} 딕셔너리
        """
        results = {}
        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            for keyword in batch:
                try:
                    related = self.get_related_keywords(keyword)
                    results[keyword] = related
                except Exception as e:
                    logger.warning("연관키워드 배치 조회 실패 (%s): %s", keyword, e)
                    results[keyword] = []

            if i + batch_size < len(keywords):
                time.sleep(delay)

        return results
