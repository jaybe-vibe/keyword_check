"""
네이버 검색광고 API 클라이언트 - 키워드 검색량 조회

API 문서: https://github.com/naver/searchad-apidoc
엔드포인트: GET https://api.searchad.naver.com/keywordstool
인증: HMAC-SHA256 서명
"""

import base64
import hashlib
import hmac
import time
import urllib.parse
import requests


BASE_URL = "https://api.searchad.naver.com"


def _safe_float(value) -> float:
    """API 응답값을 안전하게 float로 변환 (문자열 '< 10' 등 대응)"""
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


class NaverAdsAPIClient:
    """네이버 검색광고 API 클라이언트"""

    def __init__(self, customer_id: str, api_key: str, secret_key: str):
        self.customer_id = customer_id
        self.api_key = api_key
        self.secret_key = secret_key

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
        """
        키워드 검색량 조회.

        Args:
            keywords: 키워드 리스트
            show_detail: 1이면 월별 PC/모바일 상세 포함

        Returns:
            [{"relKeyword": str, "monthlyPcQcCnt": int, "monthlyMobileQcCnt": int, "compIdx": str, ...}]
        """
        uri = "/keywordstool"
        method = "GET"
        headers = self._get_headers(method, uri)

        # 네이버 API는 공백 포함 키워드를 거부하므로 공백 제거 후 전송
        cleaned = [kw.replace(" ", "") for kw in keywords]
        encoded_keywords = ",".join(urllib.parse.quote(kw) for kw in cleaned)
        url = f"{BASE_URL}{uri}?hintKeywords={encoded_keywords}&showDetail={show_detail}"

        response = requests.get(
            url,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("keywordList", [])

    def get_volumes_batched(
        self,
        keywords: list[str],
        batch_size: int = 5,
        delay: float = 0.5,
    ) -> dict:
        """
        배치 단위로 검색량 조회.

        Returns:
            {keyword: {"pc": int, "mobile": int, "total": int, "competition": str}}
        """
        results = {}

        # 공백 제거 키워드 → 원본 키워드 매핑 (API는 공백 없는 키워드를 반환)
        stripped_to_original = {}
        for kw in keywords:
            stripped_to_original[kw.replace(" ", "")] = kw

        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            try:
                api_results = self.get_keyword_volumes(batch)
                for item in api_results:
                    rel_kw = item.get("relKeyword", "")
                    pc = item.get("monthlyPcQcCnt", 0)
                    mobile = item.get("monthlyMobileQcCnt", 0)

                    # 네이버는 낮은 검색량에 "< 10" 문자열 반환
                    if isinstance(pc, str):
                        pc = 5
                    if isinstance(mobile, str):
                        mobile = 5

                    vol_data = {
                        "pc": int(pc),
                        "mobile": int(mobile),
                        "total": int(pc) + int(mobile),
                        "competition": item.get("compIdx", ""),
                        "avg_pc_clicks": _safe_float(item.get("monthlyAvePcClkCnt", 0)),
                        "avg_mobile_clicks": _safe_float(item.get("monthlyAveMobileClkCnt", 0)),
                        "avg_pc_ctr": _safe_float(item.get("monthlyAvePcCtr", 0)),
                        "avg_mobile_ctr": _safe_float(item.get("monthlyAveMobileCtr", 0)),
                        "avg_ad_count": _safe_float(item.get("plAvgDepth", 0)),
                    }

                    # 원본 키워드(공백 포함)로 매칭 시도
                    original_kw = stripped_to_original.get(rel_kw.replace(" ", ""), rel_kw)
                    results[original_kw] = vol_data

                    # 공백 없는 키워드도 추가 (원본과 다른 경우)
                    if rel_kw != original_kw:
                        results[rel_kw] = vol_data

            except Exception as e:
                for kw in batch:
                    if kw not in results:
                        results[kw] = {
                            "pc": 0,
                            "mobile": 0,
                            "total": 0,
                            "competition": "",
                            "error": str(e),
                        }

            # 배치 간 딜레이
            if i + batch_size < len(keywords):
                time.sleep(delay)

        return results

    def get_related_keywords(self, keyword: str) -> list[dict]:
        """
        키워드의 연관키워드 목록 조회 (검색량 포함).

        네이버 API는 hintKeywords로 검색하면 해당 키워드 + 연관키워드를 모두 반환.
        원본 키워드를 제외한 나머지가 연관키워드.

        Returns:
            [{"keyword": str, "pc": int, "mobile": int, "total": int,
              "competition": str, "avg_pc_clicks": float, ...}]
        """
        try:
            api_results = self.get_keyword_volumes([keyword])
        except Exception:
            return []

        cleaned_kw = keyword.replace(" ", "")
        related = []
        for item in api_results:
            rel_kw = item.get("relKeyword", "")
            # 원본 키워드 자체는 제외
            if rel_kw.replace(" ", "") == cleaned_kw:
                continue

            pc = item.get("monthlyPcQcCnt", 0)
            mobile = item.get("monthlyMobileQcCnt", 0)
            if isinstance(pc, str):
                pc = 5
            if isinstance(mobile, str):
                mobile = 5

            related.append({
                "keyword": rel_kw,
                "pc": int(pc),
                "mobile": int(mobile),
                "total": int(pc) + int(mobile),
                "competition": item.get("compIdx", ""),
                "avg_pc_clicks": _safe_float(item.get("monthlyAvePcClkCnt", 0)),
                "avg_mobile_clicks": _safe_float(item.get("monthlyAveMobileClkCnt", 0)),
                "avg_pc_ctr": _safe_float(item.get("monthlyAvePcCtr", 0)),
                "avg_mobile_ctr": _safe_float(item.get("monthlyAveMobileCtr", 0)),
                "avg_ad_count": _safe_float(item.get("plAvgDepth", 0)),
            })

        return related
