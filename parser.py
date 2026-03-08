"""
네이버 검색 결과 스마트블록 HTML 파서 (2025~2026 Fender 구조 대응)

핵심 전략:
1. div[data-fender-root]의 data-meta-area 속성으로 블록 유형 식별
2. 콘텐츠 유형(블로그/카페/인플루언서)은 URL 패턴으로 판별
3. sds-comps-* 클래스 기반 요소 추출 (안정적)
4. 연관 키워드는 href 패턴 기반 추출
"""

import re
import urllib.parse
from bs4 import BeautifulSoup, Tag
from models import SmartBlock, ContentItem, BlockType, EXCLUDED_BLOCKS, PRIORITY_BLOCKS
from config import (
    META_AREA_MAP,
    META_AREA_PREFIX,
    EXCLUDED_CATEGORIES,
    PRIORITY_CATEGORIES,
    BLOCK_SELECTORS,
    URL_PATTERNS,
    BLOCK_NAME_MAP,
)


def _identify_content_type(url: str) -> str:
    """URL 패턴으로 콘텐츠 소스 유형 식별 (classifier.get_content_type 위임)"""
    from classifier import get_content_type
    result = get_content_type(url)
    return "" if result == "기타" else result


def _url_to_block_type(url: str) -> BlockType:
    """URL로 BlockType 매핑"""
    content_type = _identify_content_type(url)
    mapping = {
        "블로그": BlockType.BLOG,
        "카페": BlockType.CAFE,
        "인플루언서": BlockType.INFLUENCER,
        "지식인": BlockType.KNOWLEDGE,
    }
    return mapping.get(content_type, BlockType.OTHER)


def _clean_items(items: list[ContentItem]) -> list[ContentItem]:
    """추출된 아이템 정리: 의미없는 항목 제거 + 제목 정리"""
    _skip = {"Keep에 바로가기", "Keep에 저장", "바로가기",
             "네이버 지식iN", "네이버지식iN", "지식iN"}
    cleaned = []
    for item in items:
        # keep.naver.com URL 제거
        if "keep.naver.com" in item.url:
            continue
        # 의미없는 제목 제거
        if item.title in _skip:
            continue
        # 제목 앞 날짜 패턴 제거 (YYYY.MM.DD.)
        stripped = re.sub(r'^\d{4}\.\d{2}\.\d{2}\.?\s*', '', item.title)
        if stripped:
            item.title = stripped
        cleaned.append(item)
    return cleaned


class NaverSearchParser:
    """네이버 검색 결과 HTML에서 스마트블록 추출"""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.debug_log: list[str] = []

    def parse(self, html: str) -> dict:
        """
        전체 페이지 HTML 파싱.

        Returns:
            {
                "blocks": list[SmartBlock],
                "related_keywords": list[str],
                "raw_block_names": list[str],
                "debug_log": list[str],
            }
        """
        self.debug_log = []
        soup = BeautifulSoup(html, "lxml")

        blocks = self._extract_blocks(soup)
        related = self._extract_related_keywords(soup)

        return {
            "blocks": blocks,
            "related_keywords": related,
            "raw_block_names": [b.block_name for b in blocks],
            "debug_log": self.debug_log,
        }

    def _extract_blocks(self, soup: BeautifulSoup) -> list[SmartBlock]:
        """Fender root 기반 블록 추출"""
        blocks = []
        position = 0

        # 전략 1: data-fender-root로 블록 찾기
        fender_roots = soup.select(BLOCK_SELECTORS["fender_root"])
        self._log(f"Fender root {len(fender_roots)}개 발견")

        for root in fender_roots:
            meta_area = root.get("data-meta-area", "")
            if not meta_area:
                continue

            category = self._resolve_meta_area(meta_area)
            if not category:
                self._log(f"  미등록 area: {meta_area}")
                continue

            # 제외 카테고리 (단, web 블록에 블로그/카페 콘텐츠가 있으면 살림)
            is_web_block = False
            if category in EXCLUDED_CATEGORIES:
                if category == "web":
                    # web 블록 내 URL로 블로그/카페/인플루언서 판별
                    detected_type = self._detect_ugc_type(root)
                    if detected_type in PRIORITY_BLOCKS:
                        self._log(f"  web 블록에 {detected_type.value} 콘텐츠 감지 → 포함")
                        is_web_block = True
                        category = "ugc"  # UGC로 재분류
                    else:
                        self._log(f"  제외: {meta_area} ({category})")
                        continue
                else:
                    self._log(f"  제외: {meta_area} ({category})")
                    continue

            # 연관 키워드 블록은 별도 처리
            if category in ("related_top", "related_bottom"):
                continue

            position += 1

            # 블록 이름 (h2 텍스트 또는 area 코드)
            block_name = self._get_block_header(root) or meta_area

            # 카테고리 → BlockType
            block_type = self._category_to_block_type(category, root)

            # UGC 블록이 OTHER로 떨어졌지만 kin 링크가 2개 이상이면 KNOWLEDGE로 재분류
            if block_type == BlockType.OTHER and category == "ugc":
                kin_count = sum(
                    1 for a in root.select("a[href]")
                    if "://kin.naver.com" in a.get("href", "")
                )
                if kin_count >= 2:
                    block_type = BlockType.KNOWLEDGE
                    self._log(f"  UGC→KNOWLEDGE 폴백 (kin 링크 {kin_count}개)")

            # 콘텐츠 추출: block_type 기반
            items = []
            if block_type in PRIORITY_BLOCKS:
                if block_type == BlockType.KNOWLEDGE:
                    items = self._extract_kin_items(root)
                elif is_web_block:
                    # web_gen 블록은 UGC와 HTML 구조가 다름
                    items = self._extract_web_items(root)
                elif block_type == BlockType.INFLUENCER:
                    items = self._extract_ugc_items(root, is_influencer=True)
                else:  # BLOG, CAFE (UGC 블록)
                    items = self._extract_ugc_items(root)
                items = _clean_items(items)

            self._log(
                f"  [{position}위] {block_name} (area={meta_area}, "
                f"type={block_type.value}, items={len(items)})"
            )

            blocks.append(SmartBlock(
                block_type=block_type,
                block_name=block_name,
                position=position,
                items=items,
                item_count=len(items),
            ))

        # 전략 2 (폴백): fender_root가 없으면 레거시 파싱
        if not blocks:
            self._log("Fender root 없음 - 레거시 파싱 시도")
            blocks = self._extract_blocks_legacy(soup)

        return blocks

    def _category_to_block_type(self, category: str, root: Tag) -> BlockType:
        """카테고리 문자열 → BlockType. UGC 블록은 내부 URL로 판별."""
        if category == "knowledge":
            return BlockType.KNOWLEDGE
        elif category == "influencer":
            return BlockType.INFLUENCER
        elif category == "news":
            return BlockType.NEWS
        elif category == "image":
            return BlockType.IMAGE
        elif category == "video":
            return BlockType.VIDEO
        elif category == "place":
            return BlockType.PLACE
        elif category == "brand":
            return BlockType.BRAND
        elif category == "ugc":
            # UGC 블록 안의 URL로 블로그/카페 판별
            return self._detect_ugc_type(root)
        return BlockType.OTHER

    def _detect_ugc_type(self, root: Tag) -> BlockType:
        """UGC 블록 내 링크 URL을 분석하여 주요 콘텐츠 유형 판별

        지식인(kin)은 여기서 판별하지 않음 → kin 전용 area 코드(ink_*, kin)로
        이미 분류되며, UGC 혼합 블록에서 kin을 세면 인플루언서가 누락됨.
        """
        type_counts = {"블로그": 0, "카페": 0, "인플루언서": 0}

        for a_tag in root.select("a[href]"):
            href = a_tag.get("href", "")
            content_type = _identify_content_type(href)
            if content_type in type_counts:
                type_counts[content_type] += 1

        # 가장 많이 등장한 유형
        if not any(type_counts.values()):
            return BlockType.OTHER

        dominant = max(type_counts, key=type_counts.get)
        mapping = {
            "블로그": BlockType.BLOG,
            "카페": BlockType.CAFE,
            "인플루언서": BlockType.INFLUENCER,
        }
        return mapping.get(dominant, BlockType.OTHER)

    def _resolve_meta_area(self, meta_area: str) -> str:
        """data-meta-area 값을 카테고리로 변환 (정확한 매핑 → 프리픽스 폴백)"""
        # 1. 정확한 매핑
        if meta_area in META_AREA_MAP:
            return META_AREA_MAP[meta_area]
        # 2. 프리픽스 매핑 (신규 area 코드 대응)
        for prefix, category in META_AREA_PREFIX.items():
            if meta_area.startswith(prefix):
                self._log(f"  프리픽스 매칭: {meta_area} → {category}")
                return category
        return ""

    def _extract_web_items(self, root: Tag) -> list[ContentItem]:
        """web_gen 블록에서 콘텐츠 추출 (blog/cafe/influencer가 웹 검색결과로 노출될 때)

        web_gen 구조:
        - 프로필: sds-comps-profile.type-web → 블로거 이름 + URL 경로
        - 제목: sds-comps-text-type-headline1
        - 날짜: sds-comps-text-left 내부 span
        - URL: 프로필 부모 <a> 태그의 href
        """
        items = []

        # 각 웹 결과 아이템은 profile.type-web 카드를 포함
        profiles = root.select("div.sds-comps-profile.type-web")
        if not profiles:
            # 폴백: 모든 프로필 카드
            profiles = root.select(BLOCK_SELECTORS["profile_card"])

        self._log(f"    web 아이템: 프로필 {len(profiles)}개 발견")

        for rank, profile in enumerate(profiles, 1):
            try:
                item = ContentItem(rank=rank)

                # 아이템 래퍼 찾기 (프로필에서 위로 탐색)
                wrapper = profile
                for _ in range(5):
                    parent = wrapper.parent
                    if not parent or parent == root:
                        break
                    # 여러 프로필을 포함하면 너무 상위로 간 것
                    if len(parent.select("div.sds-comps-profile")) > 1:
                        break
                    wrapper = parent

                # 출처 (블로거/카페 이름): profile-info-title-text
                source_elem = profile.select_one(
                    ".sds-comps-profile-info-title-text"
                )
                if source_elem:
                    # 내부에 링크가 있으면 링크 텍스트, 없으면 직접 텍스트
                    link_in_source = source_elem.select_one("a")
                    if link_in_source:
                        item.source = link_in_source.get_text(strip=True)
                    else:
                        item.source = source_elem.get_text(strip=True)

                # 제목: headline1 스타일 텍스트
                title_elem = wrapper.select_one(
                    "span.sds-comps-text-type-headline1"
                )
                if title_elem:
                    item.title = title_elem.get_text(strip=True)

                # 날짜: sds-comps-text-left 내부 span (날짜 패턴 검증)
                date_container = wrapper.select_one("span.sds-comps-text-left")
                if date_container:
                    for date_span in date_container.select("span"):
                        dt = date_span.get_text(strip=True)
                        if re.match(r'\d{4}\.\d{2}\.\d{2}', dt) or dt.endswith("전"):
                            item.date = dt
                            break

                # URL: 프로필 부모 <a> 또는 제목 부모 <a>
                profile_link = profile.find_parent("a")
                if profile_link:
                    item.url = profile_link.get("href", "")
                elif title_elem:
                    title_link = title_elem.find_parent("a")
                    if title_link:
                        item.url = title_link.get("href", "")

                if item.title:
                    items.append(item)
            except Exception:
                continue

        return items[:10]

    def _get_block_header(self, root: Tag) -> str:
        """블록의 h2 헤더 텍스트 추출"""
        for selector in BLOCK_SELECTORS["section_header"]:
            h2 = root.select_one(selector)
            if h2:
                text = h2.get_text(strip=True)
                # 불필요한 접미사 제거
                for suffix in ["더보기", "전체보기", ">"]:
                    text = text.replace(suffix, "").strip()
                if text:
                    return text
        return ""

    def _extract_ugc_items(self, root: Tag, is_influencer: bool = False) -> list[ContentItem]:
        """UGC/인플루언서 블록에서 콘텐츠 카드 추출 (다중 전략)"""
        items = []

        # === 전략 1: 알려진 컨테이너 클래스로 아이템 찾기 ===
        container_selectors = [
            "div.fds-ugc-single-intention-item-list",
            "div.fds-ugc-item-list",
            "div.fds-ugc-influencer",
            "div.fds-ugc-multi-intention-item-list",
        ]
        ugc_items = []
        used_strategy = ""

        for selector in container_selectors:
            item_list = root.select_one(selector)
            if item_list:
                ugc_items = item_list.find_all("div", recursive=False)
                if ugc_items:
                    used_strategy = f"컨테이너({selector})"
                    break

        # === 전략 2: class에 'fds-ugc' 포함된 div 탐색 ===
        if not ugc_items:
            for div in root.select("div[class]"):
                classes = " ".join(div.get("class", []))
                if "fds-ugc" in classes and "item" in classes:
                    children = div.find_all("div", recursive=False)
                    if len(children) >= 2:
                        ugc_items = children
                        used_strategy = f"fds-ugc 패턴({classes[:40]})"
                        break

        # === 전략 3: 프로필 카드 기반 아이템 탐색 ===
        if not ugc_items:
            seen_ids = set()
            profiles = root.select(BLOCK_SELECTORS["profile_card"])
            for prof in profiles:
                # 프로필에서 위로 올라가며 아이템 래퍼 찾기
                wrapper = prof
                for _ in range(5):
                    parent = wrapper.parent
                    if not parent or parent == root:
                        break
                    # 부모에 프로필 카드가 여러 개이면 너무 상위로 간 것
                    if len(parent.select(BLOCK_SELECTORS["profile_card"])) > 1:
                        break
                    wrapper = parent
                wid = id(wrapper)
                if wrapper != root and wid not in seen_ids:
                    seen_ids.add(wid)
                    ugc_items.append(wrapper)
            if ugc_items:
                used_strategy = f"프로필 카드({len(profiles)}개)"

        # === 전략 4: 콘텐츠 URL 링크 기반 ===
        if not ugc_items:
            content_patterns = []
            for patterns in URL_PATTERNS.values():
                content_patterns.extend(patterns)

            seen_ids = set()
            for a_tag in root.select("a[href]"):
                href = a_tag.get("href", "")
                text = a_tag.get_text(strip=True)
                if not href or href == "#" or not text or len(text) < 4:
                    continue
                if "keep.naver.com" in href:
                    continue
                if any(p in href for p in content_patterns):
                    # 링크에서 위로 올라가며 아이템 래퍼 찾기
                    wrapper = a_tag
                    for _ in range(4):
                        parent = wrapper.parent
                        if not parent or parent == root:
                            break
                        wrapper = parent
                    wid = id(wrapper)
                    if wid not in seen_ids:
                        seen_ids.add(wid)
                        ugc_items.append(wrapper)
            if ugc_items:
                used_strategy = f"URL 패턴({len(ugc_items)}개)"

        self._log(f"    UGC 아이템 {len(ugc_items)}개 발견 (전략: {used_strategy or '없음'})")

        # === 각 아이템에서 콘텐츠 추출 ===
        for rank, item_wrap in enumerate(ugc_items, 1):
            try:
                item = ContentItem(rank=rank)

                # 프로필 카드에서 출처/날짜 추출
                profile = item_wrap.select_one(BLOCK_SELECTORS["profile_card"])
                if profile:
                    source_link = profile.select_one(
                        BLOCK_SELECTORS["profile_source"]
                    )
                    if source_link:
                        item.source = source_link.get_text(strip=True)

                    # 날짜: subtext에서 날짜 패턴 매칭 (비날짜 텍스트 제외)
                    for subtext in profile.select(BLOCK_SELECTORS["profile_date"]):
                        dt = subtext.get_text(strip=True)
                        if re.match(r'\d{4}\.\d{2}\.\d{2}', dt) or dt.endswith("전"):
                            item.date = dt
                            break

                # 날짜 폴백: web 스타일 블록은 sds-comps-text-left에 날짜 있음
                if not item.date:
                    for text_left in item_wrap.select("span.sds-comps-text-left"):
                        for span in text_left.select("span"):
                            dt = span.get_text(strip=True)
                            if re.match(r'\d{4}\.\d{2}\.\d{2}', dt) or dt.endswith("전"):
                                item.date = dt
                                break
                        if item.date:
                            break

                # 제목: headline1 우선 (설명/snippet이 아닌 실제 제목)
                headline = item_wrap.select_one(
                    "span.sds-comps-text-type-headline1"
                )
                if headline:
                    item.title = headline.get_text(strip=True)
                    title_link = headline.find_parent("a")
                    if title_link and title_link.get("href", ""):
                        item.url = title_link.get("href", "")

                # 폴백: headline1이 없거나 URL이 없으면 링크 탐색
                # 첫 번째 콘텐츠 링크 = 제목 (인플루언서 등 headline1 없는 블록 대응)
                if not item.title or not item.url:
                    first_link = None
                    for link in item_wrap.select("a[href]"):
                        if profile and link.find_parent(
                            "div", class_=lambda c: c and "sds-comps-profile" in c
                        ):
                            continue
                        href = link.get("href", "")
                        text = link.get_text(strip=True)
                        if not href or href == "#" or "keep.naver.com" in href:
                            continue
                        if href.startswith("javascript:"):
                            continue
                        if text and len(text) > 3:
                            if first_link is None:
                                first_link = link
                    if first_link:
                        if not item.title:
                            item.title = first_link.get_text(strip=True)
                        if not item.url:
                            item.url = first_link.get("href", "")

                if item.title:
                    items.append(item)
            except Exception:
                continue

        return items[:10]

    # 의미없는 링크 텍스트 (배지, 메뉴 등)
    _SKIP_TEXTS = {"네이버 지식iN", "네이버지식iN", "지식iN",
                   "Keep에 바로가기", "Keep에 저장", "바로가기"}

    def _extract_kin_items(self, root: Tag) -> list[ContentItem]:
        """지식iN 블록에서 질문/답변 추출 (다중 전략)"""
        items = []

        # === 전략 1: kin.naver.com 질문 링크 찾기 ===
        kin_links = []
        for a_tag in root.select("a[href]"):
            href = a_tag.get("href", "")
            text = a_tag.get_text(strip=True)
            # kin.naver.com 질문 링크만 (profileLink, keep, 배지 제외)
            if ("kin.naver.com" in href
                    and "profileLink" not in href
                    and "keep.naver.com" not in href
                    and text and len(text) > 3
                    and text not in self._SKIP_TEXTS):
                kin_links.append(a_tag)

        # 중복 제거: docId 기반 (headline1 링크 우선 = 질문 제목)
        seen_keys = {}  # {dedup_key: a_tag}
        for link in kin_links:
            href = link.get("href", "")
            doc_match = re.search(r'docId=(\d+)', href)
            dedup_key = doc_match.group(1) if doc_match else href
            has_headline = link.select_one("span.sds-comps-text-type-headline1") is not None
            if dedup_key not in seen_keys:
                seen_keys[dedup_key] = link
            else:
                existing = seen_keys[dedup_key]
                existing_headline = existing.select_one("span.sds-comps-text-type-headline1") is not None
                # headline1이 있는 링크 우선 (질문 제목 > 답변/내용)
                if has_headline and not existing_headline:
                    seen_keys[dedup_key] = link

        unique_links = list(seen_keys.values())
        self._log(f"    지식iN 링크: {len(kin_links)}개 발견, {len(unique_links)}개 유니크")

        # === 전략 2: 프로필 카드 기반 아이템 탐색 (폴백) ===
        if len(unique_links) < 2:
            profiles = root.select(BLOCK_SELECTORS["profile_card"])
            self._log(f"    지식iN 프로필 카드: {len(profiles)}개 발견 (폴백)")
            for prof in profiles:
                # 프로필에서 위로 올라가며 아이템 래퍼 찾기
                wrapper = prof
                for _ in range(6):
                    parent = wrapper.parent
                    if not parent or parent == root:
                        break
                    if len(parent.select(BLOCK_SELECTORS["profile_card"])) > 1:
                        break
                    wrapper = parent

                # 래퍼에서 kin.naver.com 링크만 질문 제목으로 사용
                # (in.naver.com 인플루언서 링크 혼입 방지)
                best_link = None
                best_text = ""
                for link in wrapper.select("a[href]"):
                    if link.find_parent(
                        "div", class_=lambda c: c and "sds-comps-profile" in c
                    ):
                        continue
                    href = link.get("href", "")
                    text = link.get_text(strip=True)
                    if not href or href == "#" or not text:
                        continue
                    # kin.naver.com 링크만 허용 (지식인/인플루언서 혼합 방지)
                    if "kin.naver.com" not in href:
                        continue
                    if "keep.naver.com" in href or "profileLink" in href:
                        continue
                    if text in self._SKIP_TEXTS:
                        continue
                    if len(text) > len(best_text):
                        best_text = text
                        best_link = link

                if best_link:
                    href = best_link.get("href", "")
                    doc_match = re.search(r'docId=(\d+)', href)
                    dedup_key = doc_match.group(1) if doc_match else href
                    if dedup_key not in seen_keys:
                        seen_keys[dedup_key] = best_link
                        unique_links.append(best_link)

        # === 아이템 생성 ===
        for rank, link in enumerate(unique_links, 1):
            # 제목: headline1 텍스트 우선, 없으면 링크 전체 텍스트
            title_elem = link.select_one("span.sds-comps-text-type-headline1")
            title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)

            item = ContentItem(
                rank=rank,
                title=title,
                url=link.get("href", ""),
            )

            # 날짜와 답변자 정보: 근처 sds-comps-profile에서
            parent = link
            for _ in range(7):  # 최대 7레벨 위로 탐색
                parent = parent.parent
                if parent is None or parent == root:
                    break
                profile = parent.select_one(BLOCK_SELECTORS["profile_card"])
                if profile:
                    # 출처 (답변자 이름): 링크가 있으면 링크 텍스트, 없으면 직접 텍스트
                    source_elem = profile.select_one(
                        BLOCK_SELECTORS["profile_source"]
                    )
                    if source_elem:
                        item.source = source_elem.get_text(strip=True)
                    else:
                        # <a> 태그 없는 프로필 (일반 사용자)
                        title_text = profile.select_one(
                            ".sds-comps-profile-info-title-text"
                        )
                        if title_text:
                            item.source = title_text.get_text(strip=True)

                    # 날짜: subtext에서 날짜 패턴 매칭
                    for subtext in profile.select(".sds-comps-profile-info-subtext"):
                        text = subtext.get_text(strip=True)
                        # YYYY.MM.DD 또는 "N일 전", "N주 전" 등
                        if re.match(r'\d{4}\.\d{2}\.\d{2}', text) or text.endswith("전"):
                            item.date = text
                            break
                    break

            items.append(item)

        return items[:10]

    def _extract_related_keywords(self, soup: BeautifulSoup) -> list[str]:
        """'함께 많이 찾는' 연관 키워드 추출 (href 패턴 기반)"""
        keywords = []

        # 전략 1: href에 sm=tab_clk.ndT 포함된 링크 (상단 연관검색어)
        for link in soup.select(BLOCK_SELECTORS["related_keywords_top"]):
            kw = self._extract_query_from_href(link.get("href", ""))
            if kw and kw not in keywords:
                keywords.append(kw)

        # 전략 2: href에 sm=tab_clk.ssT 포함된 링크 (하단 함께 보면 좋은)
        for link in soup.select(BLOCK_SELECTORS["related_keywords_bottom"]):
            kw = self._extract_query_from_href(link.get("href", ""))
            if kw and kw not in keywords:
                keywords.append(kw)

        if keywords:
            self._log(f"연관키워드 {len(keywords)}개 추출 (href 패턴)")
            return keywords

        # 전략 3 (폴백): "함께" + "찾는" 텍스트를 포함하는 섹션
        for elem in soup.find_all(["h2", "span", "strong"]):
            text = elem.get_text()
            if "함께" in text and "찾는" in text:
                parent = elem.find_parent(["section", "div"])
                if parent:
                    for link in parent.select("a[href]"):
                        kw = self._extract_query_from_href(link.get("href", ""))
                        if kw and kw not in keywords:
                            keywords.append(kw)
                    if keywords:
                        self._log(f"연관키워드 {len(keywords)}개 추출 (텍스트 폴백)")
                        return keywords

        return keywords

    def _extract_query_from_href(self, href: str) -> str:
        """href에서 query= 파라미터 값 추출 (깨끗한 키워드 텍스트)"""
        if not href:
            return ""
        try:
            parsed = urllib.parse.urlparse(href)
            params = urllib.parse.parse_qs(parsed.query)
            query = params.get("query", [""])[0]
            return query.strip()
        except Exception:
            return ""

    # ============================================================
    # 레거시 파서 (Fender 구조가 없는 경우 폴백)
    # ============================================================

    def _extract_blocks_legacy(self, soup: BeautifulSoup) -> list[SmartBlock]:
        """레거시 HTML 구조 파싱 (div.api_subject_bx + h2 텍스트 매칭)"""
        blocks = []
        position = 0

        containers = soup.select("div.api_subject_bx")
        if not containers:
            for h2 in soup.find_all("h2"):
                parent = h2.find_parent(["section", "div"])
                if parent and parent not in containers:
                    containers.append(parent)

        for container in containers:
            h2 = container.select_one("h2")
            if not h2:
                continue

            text = h2.get_text(strip=True).split()[0] if h2.get_text(strip=True) else ""
            block_type = BlockType.OTHER
            for name, type_val in BLOCK_NAME_MAP.items():
                if name in text:
                    try:
                        block_type = BlockType(type_val)
                    except ValueError:
                        pass
                    break

            if block_type in EXCLUDED_BLOCKS:
                continue

            position += 1
            blocks.append(SmartBlock(
                block_type=block_type,
                block_name=text,
                position=position,
            ))

        return blocks

    def _log(self, message: str):
        if self.debug:
            self.debug_log.append(message)
