"""메뉴·게시판 이름 → 대분류.

발견(govdiscover)과 요약(digest)이 **같은 기준**을 쓰게 하려고 따로 뺐다.
예전에는 발견 쪽에만 사전이 있어서, 사전에 없는 메뉴명이 그대로 분류가 됐다.
그 결과 실측에서 분류가 **400종**까지 늘어 기간 요약이 무의미해졌다
(`외 390종 4,189건`).

지금은 두 층으로 나눈다:

  세부 이름   `국정성과` · `업무추진비` · `사전정보공표` …  → 보고서 표에 그대로
  대분류      공지 · 채용 · 입찰 · 인사 · 보도자료 · 소식 · 자료 · 정책 · 참여 · 기타
              → 기간 요약은 이 열 가지로만 센다

사전이 얕으면 '기타'가 지배한다. 실측에서 4,023건 중 2,785건(69%)이 기타로
떨어져 요약이 다시 무의미해졌다. 그래서 실제 정부 누리집 메뉴명을 훑어
갈래마다 말을 늘렸다(모집·공모·훈령·정보공개·민원·공청회 …).

세부를 버리지 않으면서 요약은 읽을 수 있게 된다. 사전에 없는 이름이 와도
대분류는 '기타'로 떨어지므로 종수가 폭발하지 않는다.
"""

from __future__ import annotations

ETC = "기타"

# 라벨로 쓰면 안 되는 앵커 텍스트 — 게시판 이름이 아니라 조작용 단어다.
# 실측에서 '전체 40건'·'더보기 38건'·'기타 78건' 이 분류 자리를 차지했다.
MEANINGLESS = frozenset(
    {
        "전체",
        "더보기",
        "더 보기",
        "바로가기",
        "바로 가기",
        "목록",
        "리스트",
        "상세",
        "상세보기",
        "자세히",
        "자세히보기",
        "본문",
        "본문내용",
        "메뉴",
        "새창",
        "새창열림",
        "새 창",
        "열기",
        "닫기",
        "이전",
        "다음",
        "처음",
        "마지막",
        "확인",
        "검색",
        "이동",
        "클릭",
        "기타",
        "etc",
        "more",
        "list",
        "view",
        "detail",
        "prev",
        "next",
    }
)


def is_meaningless(text: str) -> bool:
    """게시판 이름이 아니라 조작용 단어인가."""
    return " ".join((text or "").split()).lower() in MEANINGLESS


# 대분류 → 그 분류로 볼 말들. 순서가 우선순위다(구체적인 것을 앞에 둔다).
# '채용공고'가 '공고'보다 앞에 있어야 채용으로 잡힌다.
CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "채용",
        (
            "채용",
            "임용",
            "인재",
            "구인",
            "구직",
            "일자리",
            "모집",
            "시험",
            "자격",
            "recruit",
            "job",
        ),
    ),
    (
        "입찰",
        (
            "입찰",
            "발주",
            "계약",
            "조달",
            "제안요청",
            "낙찰",
            "수의",
            "공모",
            "지원사업",
            "bid",
            "tender",
        ),
    ),
    ("인사", ("인사발령", "인사알림", "인사정보", "인사", "전보", "표창", "포상", "명단공표")),
    ("보도자료", ("보도자료", "보도설명", "설명자료", "해명자료", "반박", "브리핑", "press")),
    ("공지", ("공지", "공고", "알림", "알립니다", "고시", "공표", "예규", "훈령", "notice")),
    ("소식", ("소식", "뉴스", "동향", "행사", "일정", "포토", "영상", "카드", "홍보", "news")),
    (
        "참여",
        (
            "참여",
            "민원",
            "신문고",
            "신고",
            "제안",
            "설문",
            "공청회",
            "의견",
            "토론",
            "소통",
            "청원",
            "고충",
            "칭찬",
            "만족도",
            "이용후기",
        ),
    ),
    (
        "자료",
        (
            "자료실",
            "자료",
            "간행물",
            "발간",
            "통계",
            "연구",
            "보고서",
            "다운로드",
            "서식",
            "교육",
            "안내",
            "faq",
            "자주묻는",
            "용어",
        ),
    ),
    (
        "정책",
        (
            "정책",
            "계획",
            "국정",
            "과제",
            "성과",
            "평가",
            "법령",
            "예산",
            "감사",
            "재정",
            "입법예고",
            "행정예고",
            "개정",
            "실명제",
            "청렴",
            "정보공개",
            "업무추진비",
            "예결산",
            "결산",
            "보조금",
            "국고",
            "국회",
            "심사",
        ),
    ),
)

# 대분류 이름들 — 요약에서 이 순서로 보여 준다.
ORDER: tuple[str, ...] = (*(name for name, _words in CATEGORY_HINTS), ETC)


def classify(text: str) -> str:
    """메뉴·게시판 이름 → 대분류(못 정하면 "")."""
    low = " ".join((text or "").split()).lower()
    if not low:
        return ""
    for category, words in CATEGORY_HINTS:
        if any(w in low for w in words):
            return category
    return ""


def canonical(text: str) -> str:
    """요약용 대분류 — 못 정하면 '기타'로 떨어뜨린다(종수 폭발 방지)."""
    return classify(text) or ETC


def from_url(url: str, fallback: str = ETC) -> str:
    """주소에서 대분류를 읽는다 — 앵커 이름이 없을 때 쓴다.

    사이트맵·경로 사이클로 찾은 게시판은 **앵커 텍스트가 없다**. 예전에는 그런
    경로를 전부 `"기타"` 로 적어서, 0KB 기관들이 그쪽으로 들어오자 실측에서
    기타가 65%(1,438/2,207)를 차지했다. 주소에도 단서가 있으니 그것을 읽는다:

      /news/notice/noticeList.do   → 공지
      /site/s_notice/jobList.jsp   → 채용
      /article/list.do?boardKey=22 → (단서 없음) 기타

    한글을 로마자로 적은 주소(`/gongji/`·`/alrim/`)도 잡는다.
    """
    # 쿼리는 보지 않는다 — `?bid=0015`(게시판 번호)가 'bid(입찰)'로 읽히는 등
    # 파라미터 이름이 우연히 분류어와 겹쳐 오판을 만든다.
    path = (url or "").split("?", 1)[0].split("#", 1)[0]
    low = path.lower()
    if not low:
        return fallback
    for category, words in CATEGORY_HINTS:
        for w in words:
            if w.isascii():
                if w in low:
                    return category
            elif (_romanized(w) and _romanized(w) in low) or w in path:
                return category
    return fallback


def _romanized(word: str) -> str:
    from .korean import romanize

    return romanize(word)
