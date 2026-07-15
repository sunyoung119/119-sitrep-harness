"""
gates.py — 결정론적 룰 게이트.

여기 남은 것은 '판단이 필요 없는' 검증뿐이다 — 참/거짓이 룰로 딱 떨어진다.
LLM 을 부르는 건 낭비이자 불안정이므로 룰로 처리한다.

  · 필수항목 존재 (HARD)  — 6항목 중 빈 값 있으면 반려
  · 시간 순서 일관성 (HARD) — datetime 비교로 순서 위반 반려
  · 개인정보 마스킹 (TRANSFORM) — 정규식으로 성명·연락처 마스킹

원인 단정 판단처럼 '뉘앙스'가 필요한 검증은 룰이 아니라 검증 에이전트
(agents.py)가 맡는다. 어디까지 룰이고 어디부터 에이전트인지 나눈 것이
이 하네스의 핵심 설계 판단이다.
"""

import re
from datetime import datetime

from schema import REQUIRED_FIELDS, TIMELINE_ORDER


class GateResult:
    PASS = "pass"
    REJECT = "reject"
    TRANSFORMED = "fix"

    def __init__(self, gate, verdict, detail, report=None):
        self.gate = gate
        self.verdict = verdict
        self.detail = detail
        self.report = report

    def __repr__(self):
        return f"[{self.gate}] {self.verdict}: {self.detail}"


# ① HARD — 필수항목 존재
def gate_required_fields(report):
    missing = [f for f in REQUIRED_FIELDS if not str(report.get(f, "")).strip()]
    if missing:
        return GateResult("필수항목", GateResult.REJECT, f"누락: {', '.join(missing)}")
    return GateResult("필수항목", GateResult.PASS, "6항목 모두 존재")


# ① HARD — 시간 순서 일관성
def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def gate_timeline(report):
    times = report.get("시각", {})
    seq = [(k, _parse(times.get(k, ""))) for k in TIMELINE_ORDER]
    present = [(k, t) for k, t in seq if t is not None]
    prev_name, prev_t = None, None
    for name, t in present:
        if prev_t is not None and t < prev_t:
            return GateResult("시간순서", GateResult.REJECT,
                              f"모순: {name}({t.strftime('%H:%M')}) < {prev_name}({prev_t.strftime('%H:%M')})")
        prev_name, prev_t = name, t
    return GateResult("시간순서", GateResult.PASS, f"검사 {len(present)}개 시각, 순서 정상")


# ③ TRANSFORM — 개인정보 마스킹
PHONE = re.compile(r"01[016789][- ]?\d{3,4}[- ]?\d{4}")
NAME = re.compile(r"(신고자|성명|이름)\s*[:：]?\s*([가-힣]{2,4})")


def gate_privacy(report):
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
        return GateResult("개인정보", GateResult.TRANSFORMED,
                          f"마스킹: {', '.join(sorted(set(changes)))}", report=new_report)
    return GateResult("개인정보", GateResult.PASS, "마스킹 대상 없음")


HARD_GATES = [gate_required_fields, gate_timeline]
TRANSFORM_GATES = [gate_privacy]
