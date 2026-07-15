"""
llm.py — 파편 무전을 상황보고 6항목 스키마로 '종합'하는 처리 단계.

OPENROUTER_API_KEY 가 있으면 실제 LLM 을, 없으면 mock 을 쓴다.
mock 은 키 없이도 하네스 전체 흐름(특히 게이트)을 눈으로 볼 수 있게 하는
교육용 모드다 — cdsa-harness 의 'mock 모드' 철학을 따른다.
"""

import json
import os

from schema import REQUIRED_FIELDS, TIMELINE_ORDER

SYSTEM = (
    "너는 소방 상황실 보고 담당이다. 아래 파편 무전을 읽고 상황보고 6항목으로 "
    "종합해 JSON 만 출력하라. 키: "
    + ", ".join(REQUIRED_FIELDS)
    + ", 시각(하위키: " + ", ".join(TIMELINE_ORDER) + ", ISO8601 또는 빈문자열). "
    "현장에서 확인 불가한 원인은 단정하지 말고, 미확인은 '미상'으로 두라. "
    "설명·마크다운 없이 JSON 객체 하나만."
)


def synthesize(radio_text, attempt=1):
    """
    파편 무전 → 6항목 보고서 dict.
    attempt: 재생성 회차(1부터). 실제 LLM 은 무시하지만,
             mock 은 이를 이용해 '1차 불완전 → 재생성 후 완전'을 시연한다.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return _synthesize_openrouter(radio_text, key)
    return _mock(radio_text, attempt)


def _synthesize_openrouter(radio_text, key):
    import urllib.request

    body = json.dumps({
        "model": os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": radio_text},
        ],
        "temperature": 0,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    content = data["choices"][0]["message"]["content"]
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(content)


# ── mock ─────────────────────────────────────────────────────────
# 결정론적 고정 출력. 게이트가 무엇을 하는지 확실히 보이도록,
# 일부러 (a) 1차엔 인명피해 누락  (b) 원인 확정형  (c) 개인정보 포함
# 을 담아둔다. 재생성(attempt>=2) 시 인명피해가 채워진다.
def _mock(radio_text, attempt):
    # 시나리오 B: 시간 모순(완진<초진) + 원인 다중 → 하드 반려/소프트 폴백 시연.
    if "[시나리오B]" in radio_text:
        return _mock_scenario_b(attempt)
    base = {
        "발생일시": "2026-07-15T14:32",
        "장소": "서울 ○○구 ○○동 △△상가 2층",
        "사고개요": (
            "2층 전기실 인근에서 발화, 누전으로 발생. 상층 연기 확산 중. "
            "신고자 김철수(010-1234-5678) 진술상 점포 내 미확인."
        ),
        "인명피해": "",  # ← 1차: 누락(하드 게이트가 반려)
        "동원현황": "펌프 3, 물탱크 1, 구급 2 / 인원 21명",
        "조치사항": "내부 진입 검색, 상층 대피 유도, 전기 차단 요청.",
        "시각": {
            "신고접수": "2026-07-15T14:32",
            "출동": "2026-07-15T14:34",
            "현장도착": "2026-07-15T14:41",
            "초진": "2026-07-15T15:03",
            "완진": "",
            "상황종료": "",
        },
    }
    if attempt >= 2:
        # 재생성: 인명피해 확인되어 채워짐(원인 확정형·개인정보는 남아 변환 게이트가 처리)
        base = dict(base)
        base["인명피해"] = "경상 1명(대피 중 연기 흡입), 사망자 없음(수색 계속)"
    return base


def _mock_scenario_b(attempt):
    # 1차: 완진(14:50)이 초진(15:03)보다 빠름 → 시간순서 하드 게이트가 반려.
    # 2차: 시각 바로잡힘. 단, 원인이 '누전'과 '방화' 둘 다 언급 → 소프트 폴백(승인).
    b = {
        "발생일시": "2026-07-15T14:32",
        "장소": "서울 ○○구 ○○동 창고",
        "사고개요": "창고 내부 발화. 누전 또는 방화 의심. 확산 빠름.",
        "인명피해": "인명피해 없음(확인 중)",
        "동원현황": "펌프 4, 화학 1 / 인원 26명",
        "조치사항": "방수 개시, 인근 대피, 위험물 확인.",
        "시각": {
            "신고접수": "2026-07-15T14:32",
            "출동": "2026-07-15T14:35",
            "현장도착": "2026-07-15T14:44",
            "초진": "2026-07-15T15:03",
            "완진": "2026-07-15T14:50",  # ← 1차: 초진보다 빠름(모순)
            "상황종료": "",
        },
    }
    if attempt >= 2:
        b = dict(b)
        b["시각"] = dict(b["시각"], **{"완진": "2026-07-15T15:21"})  # 바로잡힘
    return b
