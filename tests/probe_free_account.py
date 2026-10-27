"""Cross-check the Free-account finding against real client behaviour.

The decrypted iCubeServerData says:
    identityStr "Free", identity 0, user_pay_identity 0
    enableSoloBuilder true, enableSoloCoder true
    can_gen_solo_code false, canGenSoloCode false, permission 0
    is_credits_billing true, is_pay_freshman true

So this is a FREE account. The question that decides everything: does a Free
account get agent-mode LLM on the real client at all? If the real client also
cannot, then our 4011 is simply correct behaviour and no amount of
impersonation would help.

Evidence to gather from the plaintext logs:
  * did real chats ever complete with fee/usage recorded?
  * any quota / credit-exhausted / restriction messages?
  * what agent_type did real chats use, and did they produce output?
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
LOGS = os.path.join(APPDATA, "Trae CN", "logs")

OUT: list[str] = []

PATTERNS = {
    "credits exhausted": re.compile(
        r"credit.{0,20}(exhaust|insufficient|not enough)|"
        r"insufficient.{0,20}credit", re.I),
    "quota/limit hit": re.compile(
        r"(quota|limit).{0,30}(exceed|reach|hit)|"
        r"exceed.{0,20}(quota|limit)", re.I),
    "free/upgrade prompt": re.compile(
        r"upgrade.{0,30}(pro|plan|subscription)|"
        r"free.{0,20}(tier|plan|user)|"
        r"no permission|not entitled", re.I),
    "model restriction": re.compile(
        r"restrictedModelKeys|enforceModelAccess|ModelRestriction", re.I),
    "llm produced output": re.compile(
        r"llm_response_first_token|rs_19_llm_response_done"),
}


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    counts: Counter = Counter()
    samples: dict[str, list[str]] = {}

    for base, _d, fs in os.walk(LOGS):
        for fn in fs:
            if not fn.lower().endswith((".log", ".txt")):
                continue
            p = os.path.join(base, fn)
            try:
                if os.path.getsize(p) > 250 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    if b"\x00" in f.read(4096):
                        continue
                with io.open(p, "r", encoding="utf-8",
                             errors="replace") as f:
                    text = f.read()
            except Exception:  # noqa: BLE001
                continue
            for name, pat in PATTERNS.items():
                for m in pat.finditer(text):
                    counts[name] += 1
                    if len(samples.setdefault(name, [])) < 3:
                        s = max(0, m.start() - 200)
                        samples[name].append(
                            " ".join(text[s:m.start() + 240].split())[:420])

    log("=" * 74)
    log("A. restriction / quota signals in the REAL client's logs")
    log("=" * 74)
    for name in PATTERNS:
        log(f"\n  {name:24} x{counts[name]}")
        for s in samples.get(name, []):
            log(f"      {s}")

    log("\n" + "=" * 74)
    log("B. interpretation")
    log("=" * 74)
    log("  identity=Free, can_gen_solo_code=false, permission=0")
    log("  -> agent-mode generation is not granted to this account.")
    log("  If the real client ALSO shows restriction signals, then our 4011")
    log("  matches legitimate server behaviour and impersonation cannot help.")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_free_account.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:10000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
