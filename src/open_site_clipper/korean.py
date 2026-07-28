"""한국어 어절 정규화 — pynori(KoreanTokenizer) 코드 분석에서 증류한 최소판.

pynori를 코드 수준에서 분석한 결과(korean_tokenizer.py의 격자 탐색, TRIE 접두
검색, mecab-ko-dic 93MB의 단어·연결 비용), **품질의 원천은 알고리즘이 아니라
사전**이었다. 스타순 상위 대안(soynlp·Kiwi·KoNLPy)도 대사전·학습 말뭉치·
네이티브 코드 중 하나를 반드시 요구한다. 어느 쪽이든 이 도구의 원칙(런타임
의존성 0 · 경량 저장소)과 충돌하므로 통째로 들이지 않고 원리만 가져온다:

  차용 ① **사전 최장일치** — 단, 사전을 '단어 전체'가 아니라 어절 끝에만
        붙는 **닫힌 품사(조사·어미)** 수십 개로 축소한다. 명사는 열린
        집합이라 대사전 없이는 불가하지만, 조사·어미는 닫힌 집합이라
        완결이 가능하다. (pynori가 posAhead를 늘리며 접두 후보를 모두
        격자에 넣는 것의 1어절·접미 방향 축약.)
  차용 ② 후보가 여럿이면 가장 긴 것 — SUFFIXES를 길이 내림차순으로 검사.
  포기   격자·연결비용·복합어 분해 — 우리의 관련성 판정은 부분 문자열
        매칭이라 "채용을"·"모집합니다"는 이미 잡힌다. 이 정규화의 목적은
        digest·insight 집계에서 "지원하는/지원하며"가 "지원"으로 합쳐지는
        품질 개선이다.

단일 문자 조사(이·가·은·는·을·를·에·의·로)는 **일부러 뺐다** — '합동평가→
합동평', '새마을→새마' 같은 훼손이 실제로 나기 때문(digest.py의 기존 결정과
일치). 다문자 접미는 우연히 어간 꼬리와 겹칠 확률이 훨씬 낮다.
"""

from __future__ import annotations

# 어절 끝 닫힌 접미 — 다문자만. 최장일치를 위해 길이 내림차순 튜플로 고정.
_RAW_SUFFIXES = {
    # 조사(2자 이상)
    "에서의",
    "으로의",
    "으로써",
    "으로서",
    "에게서",
    "이라는",
    "이라며",
    "까지도",
    "부터는",
    "에서는",
    "에서도",
    "이라도",
    "이라면",
    "에서",
    "에게",
    "으로",
    "이며",
    "이자",
    "이라",
    "라는",
    "라며",
    "부터",
    "까지",
    "처럼",
    "보다",
    "마다",
    "조차",
    "마저",
    "밖에",
    "대로",
    "와의",
    "과의",
    "에는",
    "에도",
    "로는",
    "로의",
    "로써",
    "로서",
    # 용언 꼬리·어미(2자 이상, 공지 제목에서 흔한 것 위주)
    "하였습니다",
    "되었습니다",
    "했습니다",
    "합니다",
    "됩니다",
    "입니다",
    "하였다",
    "되었다",
    "하면서",
    "되면서",
    "하는",
    "되는",
    "했다",
    "된다",
    "하며",
    "되며",
    "하고",
    "되고",
    "하기",
    "되기",
    "하여",
    "되어",
    "한다",
}
SUFFIXES: tuple[str, ...] = tuple(sorted(_RAW_SUFFIXES, key=len, reverse=True))

# 접미를 뗀 뒤 남아야 하는 최소 길이 — 1자 어간은 오탐이 많아 떼지 않는다.
MIN_STEM = 2


def strip_suffix(token: str) -> str:
    """어절에서 닫힌 접미 하나를 최장일치로 뗀다. 확신이 없으면 그대로 둔다.

    예: 지원하는→지원, 플랫폼에서→플랫폼, 모집합니다→모집.
    반례 보호: 마을→마을(단일 문자 조사 안 뗌), 하는→하는(어간 1자라 안 뗌).
    """
    for suffix in SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM:
            return token[: -len(suffix)]
    return token


# ── 로마자 표기(음역) ────────────────────────────────────────────────────────
# 정부 사이트 주소에 `/gongji/`·`/alrim/` 처럼 한글을 로마자로 적은 것이 있다.
# 사전에 한글만 넣으면 이런 주소를 못 잡는다.
#
# searxng(34.5k★)가 쓰는 방법을 빌렸다 — 언어명 "français" 를 정규화한
# "francais" 를 **사전에 별칭으로 함께 등록**해 두 표기를 모두 맞춘다
# (engines/startpage.py 의 unaccented_name). 우리는 같은 발상을 한글에 적용해,
# 카테고리 단어의 로마자 표기를 별칭으로 자동 생성한다.
#
# 한글은 유니코드 배치가 규칙적이라(초성 19 × 중성 21 × 종성 28) 표준
# 라이브러리만으로 분해·변환이 된다. 사전이나 외부 패키지가 필요 없다.
_CHO = (
    "g",
    "kk",
    "n",
    "d",
    "tt",
    "r",
    "m",
    "b",
    "pp",
    "s",
    "ss",
    "",
    "j",
    "jj",
    "ch",
    "k",
    "t",
    "p",
    "h",
)
_JUNG = (
    "a",
    "ae",
    "ya",
    "yae",
    "eo",
    "e",
    "yeo",
    "ye",
    "o",
    "wa",
    "wae",
    "oe",
    "yo",
    "u",
    "wo",
    "we",
    "wi",
    "yu",
    "eu",
    "ui",
    "i",
)
_JONG = (
    "",
    "g",
    "k",
    "gs",
    "n",
    "nj",
    "nh",
    "d",
    "l",
    "lg",
    "lm",
    "lb",
    "ls",
    "lt",
    "lp",
    "lh",
    "m",
    "b",
    "bs",
    "s",
    "ss",
    "ng",
    "j",
    "c",
    "k",
    "t",
    "p",
    "h",
)
_HANGUL_BASE = 0xAC00
_HANGUL_COUNT = 11172


def romanize(text: str) -> str:
    """한글을 로마자로 옮긴다 — 주소 안의 음역 표기를 맞추기 위한 근사.

    엄밀한 국어 로마자 표기법(음운 변화 반영)이 아니라 **글자 단위 근사**다.
    주소는 대개 소리대로 적히므로 이 정도로 충분하다.

    >>> romanize("공지사항"), romanize("알림"), romanize("채용")
    ('gongjisahang', 'alrim', 'chaeyong')
    """
    out: list[str] = []
    for ch in text or "":
        code = ord(ch) - _HANGUL_BASE
        if 0 <= code < _HANGUL_COUNT:
            out.append(_CHO[code // 588] + _JUNG[(code % 588) // 28] + _JONG[code % 28])
        elif ch.isalnum():
            out.append(ch.lower())
    return "".join(out)


def romanized_aliases(word: str) -> tuple[str, ...]:
    """한 단어의 음역 별칭들 — 전체 표기와 앞 음절(축약형)."""
    full = romanize(word)
    if not full or len(full) < 3:
        return ()
    aliases = {full}
    if len(word) >= 2:
        head = romanize(word[:2])  # '공지사항' → 'gongji' 처럼 줄여 쓰는 관행
        if len(head) >= 4:
            aliases.add(head)
    return tuple(sorted(aliases))
