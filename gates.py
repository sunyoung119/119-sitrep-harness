"""
gates.py — 검증 게이트. 이 하네스의 심장.

harness = 마구(馬具). LLM 이라는 힘센 말을 정해진 길로만 가게 가두는 제약 장치다.
게이트는 제약이며, 처리 방식에 따라 세 종류로 나뉜다.

  ┌───────────┬──────────────────────────────┬─────────────────────┐
  │ 종류      │ 동작                         │ 판정 방식           │
  ├───────────┼──────────────────────────────┼─────────────────────┤
  │ HARD      │ 못 넘으면 반려 → 재생성      │ 결정론적 룰         │
  │ TRANSFORM │ 조용히 자동 수정 후 통과     │ 결정론적 룰         │
  │ SOFT      │ 애매하면 플래그 → 사람 승인  │ 룰 + 사람 판단      │
  └───────────┴──────────────────────────────┴─────────────────────┘

각 게이트는 GateResult 를 돌려주고, 오케스트레이터가 그에 따라
반려(재생성) / 변환 반영 / 사람 승인 요청 을 처리한다.
"""

import re
from datetime import datetime

from schema import REQUIRED_FIELDS, TIMELINE_ORDER


class GateResult:
    """게이트 1회 실행 결과. verdict 로 오케스트레이터가 다음 행동을 정한다."""

    PASS = "pass"          # 통과
    REJECT = "reject"      # 하드 반려 → 재생성
    TRANSFORMED = "fix"    # 변환 적용 후 통과
    NEEDS_APPROVAL = "ask" # 소프트 → 사람 승인 필요

    def __init__(self, gate, verdict, detail, report=None):
        self.gate = gate
        self.verdict = verdict
        self.detail = detail
        self.report = report  # 변환 게이트가 수정한 보고서(있으면)

    def __repr__(self):
        return f"[{self.gate}] {self.verdict}: {self.detail}"


# ────────────────────────────────────────────────────────────────
# ① HARD — 필수항목 존재
# ────────────────────────────────────────────────────────────────
def gate_required_fields(report):
    """필수 6항목 중 빈 값이 하나라도 있으면 반려."""
    missing = [f for f in REQUIRED_FIELDS if not str(report.get(f, "")).strip()]
    if missing:
        return GateResult(
            "필수항목", GateResult.REJECT,
            f"누락: {', '.join(missing)}",
        )
    return GateResult("필수항목", GateResult.PASS, "6항목 모두 존재")


# ────────────────────────────────────────────────────────────────
# ① HARD — 시간 순서 일관성
# ────────────────────────────────────────────────────────────────
def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def gate_timeline(report):
    """
    존재하는 시각들이 TIMELINE_ORDER 를 따르는지 검사.
    뒤 단계가 앞 단계보다 빠르면 시간 모순 → 반려. 결측은 통과.
    LLM 판단 없이 datetime 비교만 — 하드 게이트의 정석.
    """
    times = report.get("시각", {})
    seq = [(k, _parse(times.get(k, ""))) for k in TIMELINE_ORDER]
    present = [(k, t) for k, t in seq if t is not None]

    prev_name, prev_t = None, None
    for name, t in present:
        if prev_t is not None and t < prev_t:
            return GateResult(
                "시간순서", GateResult.REJECT,
                f"모순: {name}({t.strftime('%H:%M')}) < {prev_name}({prev_t.strftime('%H:%M')})",
            )
        prev_name, prev_t = name, t
    return GateResult("시간순서", GateResult.PASS,
                      f"검사 {len(present)}개 시각, 순서 정상")


# ────────────────────────────────────────────────────────────────
# ② TRANSFORM (+ SOFT 폴백) — 원인 유보어 강제
# ────────────────────────────────────────────────────────────────
# 현장에서는 원인을 알 수 없다. 원인은 심층 조사(감식) 후에야 나온다.
# 따라서 원인 어휘 자체는 허용하되, 유보어 없이 '확정형'으로 쓰이면
# 유보어("추정")를 자동 삽입한다. 원인이 여러 개 얽히면 기계적 삽입이
# 위험하므로 그때만 사람 승인으로 폴백한다.
CAUSE_TERMS = [
    "누전", "합선", "과전류", "전기적 요인",
    "방화", "실화", "담뱃불", "취사부주의", "불씨",
    "가스누출", "기계적 결함", "과열",
    "자연발화", "낙뢰",
]
# 유보어가 이미 붙어 있으면 정당한 서술 → 건드리지 않는다.
HEDGES = ["추정", "보임", "보인다", "가능성", "미상", "조사중", "조사 중", "의심"]


def gate_cause_hedge(report):
    text = report.get("사고개요", "")
    found = [c for c in CAUSE_TERMS if c in text]
    if not found:
        return GateResult("원인유보", GateResult.PASS, "원인 어휘 없음")

    already_hedged = any(h in text for h in HEDGES)
    if already_hedged and len(found) == 1:
        return GateResult("원인유보", GateResult.PASS,
                          f"'{found[0]}' — 유보어 확인, 정당")

    # 원인 어휘가 2개 이상 얽힘 → 기계적 삽입 위험 → 소프트 폴백
    if len(found) >= 2:
        return GateResult(
            "원인유보", GateResult.NEEDS_APPROVAL,
            f"원인 어휘 다중({', '.join(found)}) — 문장 확인 후 승인 필요",
        )

    # 원인 1개 + 유보어 없음 → 확정형 → "추정" 자동 삽입
    cause = found[0]
    fixed = re.sub(
        rf"({cause})(으로|로)?\s*(발생|발화|원인|시작)",
        rf"\1(으)로 추정",
        text,
    )
    if fixed == text:  # 패턴이 안 맞으면 어휘 뒤에 그냥 붙임
        fixed = text.replace(cause, f"{cause}(추정)", 1)

    new_report = dict(report)
    new_report["사고개요"] = fixed
    return GateResult("원인유보", GateResult.TRANSFORMED,
                      f"'{cause}' 확정형 → 유보어 삽입", report=new_report)


# ────────────────────────────────────────────────────────────────
# ③ TRANSFORM — 개인정보 마스킹 + 양식 정규화
# ────────────────────────────────────────────────────────────────
PHONE = re.compile(r"01[016789][- ]?\d{3,4}[- ]?\d{4}")
NAME = re.compile(r"(신고자|성명|이름)\s*[:：]?\s*([가-힣]{2,4})")


def gate_privacy_format(report):
    changes = []
    new_report = dict(report)

    for field, value in report.items():
        if field == "시각" or not isinstance(value, str):
            continue
        v = value
        if PHONE.search(v):
            v = PHONE.sub(lambda m: m.group()[:3] + "-****-****", v)
            changes.append("연락처")
        if NAME.search(v):
            v = NAME.sub(lambda m: f"{m.group(1)} {m.group(2)[0]}○○", v)
            changes.append("성명")
        new_report[field] = v

    if changes:
        uniq = sorted(set(changes))
        return GateResult("개인정보", GateResult.TRANSFORMED,
                          f"마스킹: {', '.join(uniq)}", report=new_report)
    return GateResult("개인정보", GateResult.PASS, "마스킹 대상 없음")


# 오케스트레이터가 순서대로 실행할 게이트 목록.
# 하드(반려 가능)를 먼저, 변환을 나중에 두어 재생성 비용을 아낀다.
GATES = [
    gate_required_fields,   # HARD
    gate_timeline,          # HARD
    gate_cause_hedge,       # TRANSFORM (+ SOFT 폴백)
    gate_privacy_format,    # TRANSFORM
]
