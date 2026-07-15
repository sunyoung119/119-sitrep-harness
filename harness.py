"""
harness.py — 상황보고 하네스 오케스트레이터.

  입력(파편 무전) → 처리(LLM 종합) → 검증(게이트 4종) → 출력(정제 보고서)

hard 게이트가 반려하면 재생성하되, 무한루프를 막기 위해 재생성 상한을 둔다
(상한 초과 시 '자동 실패 → 사람에게' 폴백). 각 단계를 로그로 펼쳐 보여준다.

사용:
    python harness.py samples/radio_01.txt
    python harness.py samples/radio_01.txt --quiet   # 로그 없이 보고서만
"""

import sys

from gates import GATES, GateResult
from llm import synthesize
from schema import REQUIRED_FIELDS, TIMELINE_ORDER

MAX_REGEN = 3  # 재생성 상한 — 이것도 harness 의 제약이다.


def log(msg, quiet):
    if not quiet:
        print(msg)


def run(radio_text, quiet=False):
    log("═" * 58, quiet)
    log("[입력] 파편 무전 수신", quiet)
    log("─" * 58, quiet)
    log(radio_text.strip(), quiet)

    report = None
    for attempt in range(1, MAX_REGEN + 1):
        log("\n" + "═" * 58, quiet)
        log(f"[처리] LLM 종합 (시도 {attempt}/{MAX_REGEN})", quiet)
        report = synthesize(radio_text, attempt=attempt)

        log("\n[검증] 게이트 통과 검사", quiet)
        log("─" * 58, quiet)
        rejected = False
        needs_human = False

        for gate in GATES:
            result = gate(report)
            _print_result(result, quiet)

            if result.verdict == GateResult.REJECT:
                rejected = True
                break  # 하드 반려 → 재생성으로
            if result.verdict == GateResult.TRANSFORMED:
                report = result.report  # 변환 반영
            if result.verdict == GateResult.NEEDS_APPROVAL:
                needs_human = True  # 소프트 → 사람 승인(데모에선 표시만)

        if not rejected:
            if needs_human:
                log("\n  ⚠ 사람 승인 대기 항목 있음 — 담당자 확인 후 확정.", quiet)
            log("\n[출력] 모든 하드 게이트 통과 → 보고서 확정", quiet)
            return report, "ok"

        log(f"\n  ✗ 하드 게이트 반려 → 재생성 (남은 시도 {MAX_REGEN - attempt})", quiet)

    log("\n[출력] 재생성 상한 초과 → 자동 처리 실패, 담당자에게 이관", quiet)
    return report, "escalated"


def _print_result(result, quiet):
    mark = {
        GateResult.PASS: "✓",
        GateResult.REJECT: "✗",
        GateResult.TRANSFORMED: "✎",
        GateResult.NEEDS_APPROVAL: "⚠",
    }[result.verdict]
    log(f"  {mark} {result.gate:<6} {result.detail}", quiet)


def render(report):
    """개조식 상황보고서 문자열."""
    lines = ["【 상황보고 】", ""]
    for f in REQUIRED_FIELDS:
        lines.append(f"ㅇ {f}: {report.get(f, '')}")
    lines.append("")
    lines.append("ㅇ 활동시각:")
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

    print("\n" + "═" * 58)
    print(render(report))
    print("═" * 58)
    print(f"상태: {status}")


if __name__ == "__main__":
    main()
