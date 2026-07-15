"""
harness.py — 상황보고 하네스 오케스트레이터.

세 LLM 에이전트와 결정론적 룰 게이트를 엮어 하나의 파이프라인으로 만든다.

  입력(파편 무전)
    → ① 종합 에이전트     : 파편 → 6항목 구조화
    → [룰 게이트·HARD]    : 필수항목·시간순서 → 위반 시 재생성
    → ② 검증 에이전트     : 원인 단정 판단 → 교정 / 사람 승인 보류
    → [룰 게이트·TRANSFORM]: 개인정보 마스킹
    → ③ 감사 에이전트     : 논리 일관성 리뷰 → 통과 / 재작성
    → 출력(정제 보고서)

에이전트(판단)와 룰 게이트(결정론)를 로그에서 구분해 보여준다.
하드 게이트/감사 반려 시 재생성하되, 무한루프를 막는 재생성 상한을 둔다.

사용:
    python harness.py samples/radio_01.txt
    python harness.py samples/radio_01.txt --quiet
"""

import sys

from agents import agent_synthesize, agent_verify_cause, agent_audit
from gates import HARD_GATES, TRANSFORM_GATES, GateResult
from schema import REQUIRED_FIELDS, TIMELINE_ORDER

MAX_REGEN = 3


def log(msg, quiet):
    if not quiet:
        print(msg)


def run(radio_text, quiet=False):
    log("=" * 60, quiet)
    log("[입력] 파편 무전 수신", quiet)
    log("-" * 60, quiet)
    log(radio_text.strip(), quiet)

    report, needs_human = None, False

    for attempt in range(1, MAX_REGEN + 1):
        needs_human = False
        log("\n" + "=" * 60, quiet)
        log(f"* 시도 {attempt}/{MAX_REGEN}", quiet)

        # (1) 종합 에이전트
        log("\n[에이전트 1.종합] 파편 무전 -> 6항목 구조화", quiet)
        report = agent_synthesize(radio_text, attempt=attempt)
        log("  -> 6항목 초안 생성 완료", quiet)

        # 룰 게이트 (HARD)
        log("\n[룰 게이트/하드] 결정론 검증", quiet)
        rejected = False
        for gate in HARD_GATES:
            r = gate(report)
            _print_gate(r, quiet)
            if r.verdict == GateResult.REJECT:
                rejected = True
                break
        if rejected:
            log(f"  X 하드 게이트 반려 -> 재생성 (남은 {MAX_REGEN - attempt})", quiet)
            continue

        # (2) 검증 에이전트
        log("\n[에이전트 2.검증] 원인 단정/과장 판단", quiet)
        v = agent_verify_cause(report.get("사고개요", ""))
        log(f"  판단: {v['verdict']} - {v['reason']}", quiet)
        if v["verdict"] == "fix":
            report = dict(report); report["사고개요"] = v["fixed"]
            log("  -> 유보어 삽입 교정 반영", quiet)
        elif v["verdict"] == "hold":
            needs_human = True
            log("  -> 사람 승인 보류 표시", quiet)

        # 룰 게이트 (TRANSFORM)
        log("\n[룰 게이트/변환] 개인정보 마스킹", quiet)
        for gate in TRANSFORM_GATES:
            r = gate(report)
            _print_gate(r, quiet)
            if r.verdict == GateResult.TRANSFORMED:
                report = r.report

        # (3) 감사 에이전트
        log("\n[에이전트 3.감사] 논리 일관성 리뷰", quiet)
        a = agent_audit(report)
        for n in a["notes"]:
            log(f"  . {n}", quiet)
        if a["verdict"] == "revise":
            log(f"  X 감사 반려 -> 재생성 (남은 {MAX_REGEN - attempt})", quiet)
            continue
        log("  O 감사 통과", quiet)

        # 완료
        if needs_human:
            log("\n! 사람 승인 대기 항목 있음 - 담당자 확인 후 확정.", quiet)
        log("\n[출력] 전 단계 통과 -> 보고서 확정", quiet)
        return report, "ok"

    log("\n[출력] 재생성 상한 초과 -> 자동 처리 실패, 담당자 이관", quiet)
    return report, "escalated"


def _print_gate(r, quiet):
    mark = {GateResult.PASS: "O", GateResult.REJECT: "X", GateResult.TRANSFORMED: "~"}[r.verdict]
    log(f"  {mark} {r.gate:<6} {r.detail}", quiet)


def render(report):
    lines = ["[ 상황보고 ]", ""]
    for f in REQUIRED_FIELDS:
        lines.append(f"o {f}: {report.get(f, '')}")
    lines.append("")
    lines.append("o 활동시각:")
    for k in TIMELINE_ORDER:
        t = report.get("시각", {}).get(k, "")
        lines.append(f"   - {k}: {t or '미상'}")
    return "\n".join(lines)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    if not args:
        print("사용: python harness.py <무전파일> [--quiet]")
        sys.exit(1)
    with open(args[0], encoding="utf-8") as f:
        radio_text = f.read()
    report, status = run(radio_text, quiet=quiet)
    print("\n" + "=" * 60)
    print(render(report))
    print("=" * 60)
    print(f"상태: {status}")


if __name__ == "__main__":
    main()
