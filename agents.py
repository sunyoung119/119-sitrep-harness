"""
agents.py — LLM 에이전트 계층.

이 하네스는 '에이전트'와 '룰 게이트'를 나눠 쓴다. 설계 원칙:

  · 결정론으로 딱 떨어지는 검증(필수항목 존재, 시각 비교, 개인정보 정규식)
    → 룰 게이트 (gates.py). LLM 을 부르는 건 낭비이자 불안정.
  · 판단·뉘앙스가 필요한 검증(원인 단정이 애매한가, 보고서가 논리적으로
    말이 되는가) → LLM 에이전트. 룰로는 못 잡는다.

세 에이전트가 협업한다:
  ① 종합(Synthesizer) — 파편 무전 → 6항목 구조화
  ② 검증(Verifier)    — 원인 단정·과장 표현을 판단하고 교정/보류
  ③ 감사(Auditor)     — 최종 보고서의 논리 일관성·품질 리뷰

각 에이전트는 OPENROUTER_API_KEY 가 있으면 실제 LLM 을, 없으면 mock 을 쓴다.
mock 도 '근거를 대며 판단하는' 형태로 출력해, 키 없이도 멀티에이전트
협업 흐름을 눈으로 확인할 수 있다.
"""

import json
import os

from schema import REQUIRED_FIELDS, TIMELINE_ORDER

MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")


def _call_openrouter(system, user, key):
    import urllib.request

    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
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
    content = data["choices"][0]["message"]["content"].strip()
    return content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _key():
    return os.environ.get("OPENROUTER_API_KEY")


# ════════════════════════════════════════════════════════════════
# ① 종합 에이전트 — 파편 무전 → 6항목 스키마
# ════════════════════════════════════════════════════════════════
SYNTH_SYSTEM = (
    "너는 소방 상황실 보고 담당이다. 파편 무전을 상황보고 6항목으로 종합해 "
    "JSON 만 출력하라. 키: " + ", ".join(REQUIRED_FIELDS) +
    ", 시각(하위키: " + ", ".join(TIMELINE_ORDER) + ", ISO8601 또는 빈문자열). "
    "현장에서 확인 불가한 원인은 단정하지 말라. 설명 없이 JSON 하나만."
)


def agent_synthesize(radio_text, attempt=1):
    key = _key()
    if key:
        return json.loads(_call_openrouter(SYNTH_SYSTEM, radio_text, key))
    return _mock_synth(radio_text, attempt)


# ════════════════════════════════════════════════════════════════
# ② 검증 에이전트 — 원인 단정·과장 표현 판단
# ════════════════════════════════════════════════════════════════
# 현장에서는 원인을 알 수 없다(감식 후에야 나옴). 룰로는 "누전으로 발생"은
# 잡아도 "화재는 전기적 문제에서 비롯된 것으로 판단됨" 같은 우회 단정은
# 못 잡는다. 이런 뉘앙스 판단이 이 에이전트의 몫이다.
VERIFY_SYSTEM = (
    "너는 소방 상황보고 검증관이다. 아래 '사고개요'에서 화재 원인을 확정적으로 "
    "단정했는지 판단하라. 현장 단계에서 원인 단정은 금물이며, 원인 언급은 반드시 "
    "'추정/미상/조사중' 등 유보 표현을 동반해야 한다. "
    "다음 JSON 만 출력: {\"verdict\": \"ok|fix|hold\", \"reason\": \"판단 근거 한 줄\", "
    "\"fixed\": \"교정된 사고개요(fix일 때만, 아니면 원문)\"}. "
    "verdict=ok: 문제없음 / fix: 확정형이라 유보어 삽입해 교정 / "
    "hold: 원인이 복수라 기계 교정 위험, 사람 승인 필요."
)


def agent_verify_cause(overview):
    key = _key()
    if key:
        return json.loads(_call_openrouter(VERIFY_SYSTEM, overview, key))
    return _mock_verify(overview)


# ════════════════════════════════════════════════════════════════
# ③ 감사 에이전트 — 최종 보고서 논리 일관성 리뷰
# ════════════════════════════════════════════════════════════════
AUDIT_SYSTEM = (
    "너는 상황보고 감사관이다. 완성된 보고서를 읽고 논리적 정합성만 본다. "
    "예: 인명피해와 조치사항이 모순되는가, 동원현황이 사고규모에 비해 비는가, "
    "개요와 시각이 어긋나는가. 문체·양식은 보지 않는다. "
    "다음 JSON 만 출력: {\"verdict\": \"pass|revise\", "
    "\"notes\": [\"발견사항\", ...]}. revise 는 명백한 논리 모순이 있을 때만."
)


def agent_audit(report):
    key = _key()
    payload = json.dumps(report, ensure_ascii=False)
    if _key():
        return json.loads(_call_openrouter(AUDIT_SYSTEM, payload, _key()))
    return _mock_audit(report)


# ════════════════════════════════════════════════════════════════
# mock — 키 없이 멀티에이전트 흐름을 시연하기 위한 결정론적 대역
# ════════════════════════════════════════════════════════════════
def _mock_synth(radio_text, attempt):
    if "[시나리오B]" in radio_text:
        return _mock_synth_b(attempt)
    base = {
        "발생일시": "2026-07-15T14:32",
        "장소": "서울 ○○구 ○○동 △△상가 2층",
        "사고개요": (
            "2층 전기실 인근에서 발화, 누전으로 발생. 상층 연기 확산 중. "
            "신고자 김철수(010-1234-5678) 진술상 점포 내 미확인."
        ),
        "인명피해": "",  # 1차 누락 → 룰 게이트가 반려
        "동원현황": "펌프 3, 물탱크 1, 구급 2 / 인원 21명",
        "조치사항": "내부 진입 검색, 상층 대피 유도, 전기 차단 요청.",
        "시각": {
            "신고접수": "2026-07-15T14:32", "출동": "2026-07-15T14:34",
            "현장도착": "2026-07-15T14:41", "초진": "2026-07-15T15:03",
            "완진": "", "상황종료": "",
        },
    }
    if attempt >= 2:
        base = dict(base)
        base["인명피해"] = "경상 1명(대피 중 연기 흡입), 사망자 없음(수색 계속)"
    return base


def _mock_synth_b(attempt):
    b = {
        "발생일시": "2026-07-15T14:32", "장소": "서울 ○○구 ○○동 창고",
        "사고개요": "창고 내부 발화. 누전 또는 방화 의심. 확산 빠름.",
        "인명피해": "인명피해 없음(확인 중)",
        "동원현황": "펌프 4, 화학 1 / 인원 26명",
        "조치사항": "방수 개시, 인근 대피, 위험물 확인.",
        "시각": {
            "신고접수": "2026-07-15T14:32", "출동": "2026-07-15T14:35",
            "현장도착": "2026-07-15T14:44", "초진": "2026-07-15T15:03",
            "완진": "2026-07-15T14:50", "상황종료": "",  # 초진보다 빠름(모순)
        },
    }
    if attempt >= 2:
        b = dict(b)
        b["시각"] = dict(b["시각"], **{"완진": "2026-07-15T15:21"})
    return b


# 검증 에이전트 mock: 원인 어휘/유보어를 '판단'하는 것처럼 근거를 대고 결정.
_CAUSE = ["누전", "합선", "과전류", "방화", "실화", "담뱃불", "가스누출", "과열",
          "자연발화", "낙뢰", "전기적"]
_HEDGE = ["추정", "보임", "보인다", "가능성", "미상", "조사중", "조사 중", "의심"]


def _mock_verify(overview):
    found = [c for c in _CAUSE if c in overview]
    if not found:
        return {"verdict": "ok", "reason": "원인 언급 없음 — 단정 위험 없음", "fixed": overview}
    if len(found) >= 2:
        return {"verdict": "hold",
                "reason": f"원인 복수 언급({', '.join(found)}) — 기계 교정 시 의미 훼손 위험, 담당자 확인 필요",
                "fixed": overview}
    hedged = any(h in overview for h in _HEDGE)
    if hedged:
        return {"verdict": "ok",
                "reason": f"'{found[0]}'에 유보 표현 동반 — 정당한 현장 판단", "fixed": overview}
    cause = found[0]
    fixed = overview
    for suf in ["으로 발생", "로 발생", "으로 발화", "로 발화", "이 원인", "가 원인"]:
        if cause + suf.replace("이 ", "").replace("가 ", "") in overview or (cause + suf) in overview:
            fixed = overview.replace(cause + suf, f"{cause}(으)로 추정")
            break
    if fixed == overview:
        fixed = overview.replace(cause, f"{cause}(추정)", 1)
    return {"verdict": "fix",
            "reason": f"'{cause}' 확정형 서술 — 유보어 삽입 필요", "fixed": fixed}


def _mock_audit(report):
    notes = []
    casualties = report.get("인명피해", "")
    actions = report.get("조치사항", "")
    if "사망" in casualties and "구조" not in actions and "이송" not in actions and "대피" not in actions:
        notes.append("사망 언급 대비 인명 관련 조치 기술이 비어 있음 — 확인 요망")
    if not notes:
        notes.append("인명피해·조치사항·동원현황 간 명백한 논리 모순 없음")
    # mock 은 명백한 모순만 revise. 데모 샘플은 통과하도록 설계.
    return {"verdict": "pass", "notes": notes}
