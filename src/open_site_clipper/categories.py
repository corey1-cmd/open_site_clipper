"""메뉴·게시판 이름 → 대분류.

발견(govdiscover)과 요약(digest)이 **같은 기준**을 쓰게 하려고 따로 뺐다.
예전에는 발견 쪽에만 사전이 있어서, 사전에 없는 메뉴명이 그대로 분류가 됐다.
그 결과 실측에서 분류가 **400종**까지 늘어 기간 요약이 무의미해졌다
(`외 390종 4,189건`).

지금은 두 층으로 나눈다:

  세부 이름   `국정성과` · `업무추진비` · `사전정보공표` …  → 보고서 표에 그대로
  대분류      입학 · 장학 · 학사(학교) · 채용 · 입찰 · 인사 · 보도자료 · 공지 ·
              소식 · 참여 · 자료 · 정책 · 기타 → 기간 요약은 이 갈래로만 센다

사전이 얕으면 '기타'가 지배한다. 실측에서 4,023건 중 2,785건(69%)이 기타로
떨어져 요약이 다시 무의미해졌다. 그래서 실제 정부 누리집 메뉴명을 훑어
갈래마다 말을 늘렸다(모집·공모·훈령·정보공개·민원·공청회 …).

세부를 버리지 않으면서 요약은 읽을 수 있게 된다. 사전에 없는 이름이 와도
대분류는 '기타'로 떨어지므로 종수가 폭발하지 않는다.
"""

from __future__ import annotations

import re

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
        "read",
        "read more",
        "view more",
        "more+",
        "+more",
        "+",
        "더보기+",
        "+더보기",
        # '+ 전체목록보기' · '노사상생 게시판' — 실측 경로 캐시에서
        "보기",
        "게시판",
    }
)


def is_meaningless(text: str) -> bool:
    """게시판 이름이 아니라 조작용 단어인가."""
    return " ".join((text or "").split()).lower() in MEANINGLESS


def strip_meaningless(text: str) -> str:
    """'HUFS Professors 더보기' → 'HUFS Professors' — 앞뒤의 조작용 단어만 뗀다."""
    words = " ".join((text or "").split()).split(" ")
    while words and words[-1].lower() in MEANINGLESS:
        words.pop()
    while words and words[0].lower() in MEANINGLESS:
        words.pop(0)
    return " ".join(words)


_GLUE_WORDS = tuple(sorted({w.replace(" ", "") for w in MEANINGLESS}, key=len, reverse=True))
# '공지사항(목록)' · '뉴스룸 게시판목록' · '일반공지목록' — 페이지 제목에 붙는 '목록' 꼬리.
_LIST_TAIL_RE = re.compile(r"\s*[(\[]?\s*(?:게시판\s*)?목록\s*[)\]]?$")
# '그림자의+밤' — 주소에서 온 이름의 '+'(공백).
_PLUS_SPACE_RE = re.compile(r"(?<=[가-힣])\+(?=[가-힣])")


def _glued_meaningless(text: str) -> bool:
    """'더보기READ'·'readmore' — 조작용 단어만 붙여 쓴 말인가."""
    s = (text or "").replace(" ", "").lower()
    if not s:
        return False
    ok = [True] + [False] * len(s)  # ok[i]: s[:i] 를 조작용 단어로 다 나눌 수 있다
    for i in range(1, len(s) + 1):
        ok[i] = any(s[:i].endswith(w) and ok[i - len(w)] for w in _GLUE_WORDS)
    return ok[-1]


def tidy_label(text: str) -> str:
    """게시판 이름을 화면에 보일 만하게 — 못 쓰는 이름이면 "".

    실측 경로 캐시에 '공지사항(목록)'·'뉴스룸 게시판목록'·'더보기READ' 같은 이름이
    남아, 갈래를 말하는 제목이 없는 글에 그 이름이 그대로 분류로 찍혔다.
    """
    flat = _PLUS_SPACE_RE.sub(" ", " ".join((text or "").split()))
    if _glued_meaningless(flat):  # '더 보기' — 떼기 전에 통째로 본다('보기'만 떼면 '더')
        return ""
    flat = strip_meaningless(flat)
    if not flat or _glued_meaningless(flat):
        return ""
    return _LIST_TAIL_RE.sub("", flat).strip()  # '게시판목록' 뿐이면 이름이 없는 것


def is_named(label: str) -> bool:
    """게시판에 이름이 있는가 — '공지사항'·'등록금심의위원회'는 예, 'READ'·'기타'는 아니오.

    이름이 있는 게시판은 이름을 믿고, 이름을 모를 때만 글 제목으로 이름을 짓는다.
    ('기타'는 발견 단계에서 이름을 모를 때 붙이는 자리표시다.)
    """
    return bool(tidy_label(label))


# 대분류 → 그 분류로 볼 말들. 순서가 우선순위다(구체적인 것을 앞에 둔다).
# '채용공고'가 '공고'보다 앞에 있어야 채용으로 잡힌다.
#
# 학교 갈래(입학·장학·학사)가 맨 앞이다. 학교 게시판은 '신입생 모집'·'장학생
# 모집'처럼 '모집'을 쓰는데, 채용보다 뒤에 두면 전부 채용으로 빨려 들어간다.
# '학사 시험 일정'도 채용(시험)이 아니라 학사다.
CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("입학", ("입학", "입시", "신입생", "편입", "admission")),
    ("장학", ("장학", "학자금", "scholarship")),
    (
        "학사",
        (
            "학사",
            "수강",
            "졸업",
            "학적",
            "휴학",
            "복학",
            "계절학기",
            "academic",
        ),
    ),
    (
        "채용",
        (
            "채용",
            "임용",
            "인재",
            "구인",
            "구직",
            "일자리",
            "취업",
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


# 게시판 이름만으로 글의 갈래가 정해지는 대분류. '장학공지' 게시판의 글은 제목이
# 무엇이든 장학이다. 나머지(공지·소식·자료·기타·'READ' 같은 앵커 원문)는 게시판
# 이름이 갈래를 말해 주지 않으므로 글 제목을 본다.
SPECIFIC = frozenset({"입학", "장학", "학사", "채용", "입찰", "인사", "보도자료"})

# 글 **제목**으로 갈래를 정할 때 쓰는 강한 말만. 메뉴 사전(CATEGORY_HINTS)을 제목에
# 그대로 쓰면 '안내'(자료)·'모집'(채용)·'행사'(소식)처럼 거의 모든 제목에 들어가는
# 말이 갈래를 정해 버린다(실측: '의료통역예비과정 교육안내' → 자료). 제목에서는 그
# 글이 무엇인지 분명히 말하는 말만 본다. 순서가 우선순위다 —
# '국가근로장학생 모집'은 장학, '입학처 계약직 직원 채용'은 채용.
#
# '장려금' 하나만으로는 장학이 아니다(국세청 '근로장려금', 고용노동부 '고용장려금').
# 한국장학재단의 '고교 취업연계 장려금'만 사업 이름째로 넣는다 — 안 넣으면 '취업'
# 때문에 채용으로 간다(실측).
TITLE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "장학",
        ("장학", "학자금", "국가근로", "취업연계 장려금", "취업연계장려금", "scholarship"),
    ),
    (
        "채용",
        ("채용", "임용", "공채", "구인", "인턴", "취업", "일자리", "recruit"),
    ),
    (
        "입학",
        (
            "입학",
            "입시",
            "신입생",
            "편입",
            "수시모집",
            "정시모집",
            "수시 모집",
            "정시 모집",
            "모집요강",
            "admission",
        ),
    ),
    (
        "학사",
        (
            "수강",
            "졸업",
            "학적",
            "휴학",
            "복학",
            "계절학기",
            "성적",
            "학위",
            "전과",
            "복수전공",
            "부전공",
            "등록금",
            "학사",
        ),
    ),
    ("입찰", ("입찰", "낙찰", "견적", "제안요청", "수의계약", "계약공고")),
    ("인사", ("인사발령", "인사 발령", "승진")),
    ("보도자료", ("보도자료", "보도설명", "해명자료")),
)


def for_title(title: str) -> str:
    """글 제목 → 대분류(강한 말이 없으면 "")."""
    low = " ".join((title or "").split()).lower()
    if not low:
        return ""
    for category, words in TITLE_HINTS:
        if any(w in low for w in words):
            return category
    return ""


def notice_category(board_label: str, title: str) -> str:
    """글 하나의 갈래 — 게시판이 갈래를 말하면 게시판, 아니면 제목.

    학교는 장학·학사 공지를 '공지사항' 한 게시판에 올리는 곳이 많다. 게시판 이름만
    쓰면 그런 글이 전부 '공지'로 묻혀 [장학]으로 거를 수가 없었다.
    """
    if canonical(board_label) in SPECIFIC:
        return board_label
    return for_title(title) or board_label


def dominant(titles: list[str], *, share: float = 0.6, minimum: int = 2) -> str:
    """제목들에서 우세한 갈래 — 게시판 이름을 모를 때 내용으로 이름을 붙인다.

    홈의 탭마다 'READ'·'더보기'만 달린 학교가 있다(한국외대: 공지·학사·장학·채용
    네 게시판이 전부 'READ'). 장학 게시판은 제목의 대부분에 '장학'이 들어가므로
    내용으로 알아볼 수 있다. 섞인 게시판(일반 공지)은 이름을 붙이지 않는다("").

    문턱이 60%인 까닭: 장학 기관의 **일반 공지**도 절반쯤은 학자금 글이다(한국장학재단
    실측 ~45%). 40%로 두었더니 그 게시판이 '장학'이 되어 창업센터 입주기업 공지까지
    장학으로 분류됐다. 이름을 붙이지 않아도 글마다 제목으로 다시 나누므로 잃는 것은 없다.
    """
    counts: dict[str, int] = {}
    total = 0
    for t in titles:
        total += 1
        c = for_title(t)
        if c:
            counts[c] = counts.get(c, 0) + 1
    if not counts:
        return ""
    rank = {name: i for i, (name, _w) in enumerate(TITLE_HINTS)}
    best, n = max(counts.items(), key=lambda kv: (kv[1], -rank[kv[0]]))
    return best if n >= minimum and n >= share * total else ""


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
            elif w in path or any(a in low for a in _romanized(w)):
                return category
    return fallback


def _romanized(word: str) -> tuple[str, ...]:
    """음역 별칭 — 글자대로(hagsa)와 소리대로(haksa) 둘 다."""
    from .korean import romanized_aliases

    return romanized_aliases(word)
