"""
설정 관리 - JSON 파일 + .env 환경변수

설정 우선순위: config.json > 기본값
API 키 등 민감 정보: .env 파일
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
CONFIG_PATH = PROJECT_ROOT / "config.json"

# .env 로드
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

DEFAULT_CONFIG = {
    "min_delay": 3.0,
    "max_delay": 8.0,
    "context_rotation_interval": 12,
    "scroll_delay": 1.5,
    "page_load_timeout": 15000,
    "headed": True,
    "output_dir": "data",
}


def load_config() -> dict:
    """config.json 로드, 기본값과 병합"""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
            config.update(saved)
    return config


def save_config(config: dict):
    """config.json 저장"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_naver_ads_credentials() -> tuple:
    """네이버 검색광고 API 인증 정보 반환 (customer_id, api_key, secret_key)"""
    return (
        os.environ.get("NAVER_CUSTOMER_ID", ""),
        os.environ.get("NAVER_API_KEY", ""),
        os.environ.get("NAVER_SECRET_KEY", ""),
    )


# ============================================================
# 네이버 HTML 구조 매핑 (2025~2026 현재 기준)
#
# 네이버는 "Fender" 렌더링 프레임워크를 사용하며,
# data-meta-area 속성으로 블록 유형을 식별할 수 있다.
# 콘텐츠 유형(블로그/카페/인플루언서)은 URL 패턴으로 판별.
# ============================================================

# data-meta-area 값 → 블록 카테고리 매핑
META_AREA_MAP = {
    # UGC 의도 블록 (블로그+카페 혼합) - 주제별로 여러 개 나타남
    "ugB_b1R": "ugc",
    "ugB_b2R": "ugc",
    "ugB_b3R": "ugc",
    "ugB_b4R": "ugc",
    "ugB_b5R": "ugc",
    # 인플루언서 참여 콘텐츠
    "ugB_ipR": "influencer",
    # 브랜드 콘텐츠 (광고)
    "ugB_adR": "brand",
    # 지식iN
    "kin": "knowledge",
    # 인플루언서 (ink_kid: data-meta-ssuid="influencer", block-id에 influencer 포함)
    "ink_kid": "influencer",
    # urB_ 계열 (Universal Result Block)
    "urB_boR": "ugc",
    "urB_coR": "ugc",
    "urB_imM": "image",
    # 관련 키워드 (함께 많이 찾는)
    "kwX_ndT": "related_top",
    # 함께 보면 좋은
    "kwL_ssT": "related_bottom",
    # 쇼핑
    "shp_gui": "shopping",
    "shs_lis": "shopping",
    # 웹사이트
    "sit_4po": "web",
    "web_gen": "web",
    # 파워링크
    "pwl_nop": "powerlink",
    # 뉴스
    "nws": "news",
    # 이미지
    "img": "image",
    # 동영상
    "vdo": "video",
    # 플레이스
    "plc": "place",
}

# 프리픽스 기반 area 매핑 (META_AREA_MAP에 없는 신규 코드 대응)
# 순서 중요: 더 구체적인 프리픽스가 앞에 와야 함
META_AREA_PREFIX = {
    # ugB_ 계열 (UGC Block)
    "ugB_ip": "influencer",   # 인플루언서 참여 콘텐츠
    "ugB_ad": "brand",        # 브랜드/광고 콘텐츠
    "ugB_": "ugc",            # 기타 모든 UGC 블록
    # urB_ 계열 (Universal Result Block - ugB_와 동일한 역할)
    "urB_ip": "influencer",   # 인플루언서
    "urB_ad": "brand",        # 브랜드/광고
    "urB_im": "image",        # 이미지 (urB_imM 등)
    "urB_": "ugc",            # 기타 모든 urB_ 블록 (urB_boR, urB_coR 등)
    # 지식iN 계열
    "ink_": "ugc",            # ink_ 계열 (ink_kid=인플루언서, URL로 판별)
    "kin": "knowledge",
    "nws": "news",
    "shp": "shopping",
    "shs": "shopping",
    "pwl": "powerlink",
    "vdo": "video",
    "img": "image",
    "plc": "place",
    "sit": "web",
    "web": "web",
    "kwX": "related_top",
    "kwL": "related_bottom",
}

# 제외할 카테고리 (분석 대상 아님)
EXCLUDED_CATEGORIES = {"shopping", "powerlink", "web", "brand"}

# 우선 카테고리 (상세 콘텐츠 추출 대상)
PRIORITY_CATEGORIES = {"ugc", "influencer", "knowledge"}

# CSS 셀렉터 (안정적인 것 위주)
BLOCK_SELECTORS = {
    # 블록 컨테이너
    "section_container": [
        "div.api_subject_bx",
    ],
    # Fender root (data-meta-area 포함)
    "fender_root": "div[data-fender-root]",
    # 헤더
    "section_header": [
        "h2.sds-comps-text",
        "h2",
    ],
    # 프로필 카드 (UGC/인플루언서 콘텐츠 아이템)
    "profile_card": "div.sds-comps-profile",
    # 프로필 내 요소
    "profile_source": ".sds-comps-profile-info-title-text a",
    "profile_date": ".sds-comps-profile-info-subtext",
    # 관련 키워드 (href 패턴 기반 - 가장 안정적)
    "related_keywords_top": 'a[href*="sm=tab_clk.ndT"]',
    "related_keywords_bottom": 'a[href*="sm=tab_clk.ssT"]',
}

# URL 패턴으로 콘텐츠 소스 식별
URL_PATTERNS = {
    "블로그": ["blog.naver.com", "m.blog.naver.com", "post.naver.com"],
    "카페": ["cafe.naver.com", "m.cafe.naver.com"],
    "지식인": ["kin.naver.com"],
    "인플루언서": ["in.naver.com"],
}

# 레거시 호환: 블록 이름 매핑 (h2 텍스트 → BlockType)
BLOCK_NAME_MAP = {
    "블로그": "블로그",
    "카페": "카페",
    "인플루언서": "인플루언서",
    "지식iN": "지식인",
    "지식인": "지식인",
    "뉴스": "뉴스",
    "이미지": "이미지",
    "동영상": "동영상",
    "VIEW": "VIEW",
    "파워링크": "파워링크",
    "쇼핑": "쇼핑",
    "네이버플러스 스토어": "네이버플러스 스토어",
    "가격비교": "가격비교",
    "브랜드콘텐츠": "브랜드콘텐츠",
    "브랜드 콘텐츠": "브랜드콘텐츠",
}
