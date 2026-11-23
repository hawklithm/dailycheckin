"""Recover the COMPLETE field lists of the real chat structs.

The previous pass found serde's own declaration strings, e.g.

    ...assistant_message_id message_content code_selections ... workroom_id
    hit_shared_artifact_and_workroom  struct ChatArgs with 61 elements

so the field list sits immediately BEFORE the "struct ChatArgs with 61
elements" marker, concatenated with no separators. That gives us the real
schema instead of guesses.

This extracts, for every interesting struct, the run of field names preceding
its declaration, then splits it against the known field vocabulary so the
result is readable.
"""
from __future__ import annotations

import io
import os
import re
import sys

DLL = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
       r"\resources\app\modules\ai-agent\ai_agent.dll")

TARGETS = [
    "ChatArgs", "ModelExtraConfig", "CustomModel", "ChatMessageData",
    "InitialMessage", "ApplicationConfig", "ModelDisplayConfig",
    "StandardChatMessagePart", "ChatArgsAgentInfo", "SendMsgToChatArgs",
    "ModelSmartSelection", "PersistCustomModelMeta", "Request", "Response",
    "ToolCall", "SessionData", "SlashGetRequest", "GetModelListRequest",
    "ChatMemoryConfig", "ModelCommercialInfo", "ModelSelectionModeConfig",
]

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    with io.open(DLL, "rb") as f:
        buf = f.read()

    # collect every declared struct name so we can split runs reliably
    decl = re.compile(rb"struct ([A-Za-z0-9_]{2,60}) with (\d+) element")
    declared = set()
    for m in decl.finditer(buf):
        declared.add(m.group(1).decode("ascii", "replace"))
    # also common non-struct tokens that appear in these runs
    extra = {"None", "Some", "true", "false", "struct", "with", "elements",
             "element", "enum", "variant", "field", "Option", "String"}
    vocab = sorted(declared | extra, key=len, reverse=True)
    log(f"vocabulary: {len(vocab)} declared struct names\n")

    def split_fields(run: str) -> list[str]:
        """Greedy longest-match split of a concatenated field run."""
        out: list[str] = []
        i = 0
        while i < len(run):
            for tok in vocab:
                if run.startswith(tok, i):
                    out.append(tok)
                    i += len(tok)
                    break
            else:
                # consume one char as part of an unknown field name
                j = i + 1
                while j < len(run) and not any(run.startswith(t, j)
                                               for t in vocab):
                    j += 1
                out.append(run[i:j])
                i = j
        return out

    for target in TARGETS:
        marker = f"struct {target} with ".encode()
        p = buf.find(marker)
        if p < 0:
            log(f"### {target}: NOT FOUND")
            continue
        # arity
        eol = buf.find(b" element", p)
        arity = buf[p + len(marker):eol].decode("ascii", "replace")
        # walk back to the enclosing printable run
        i = p
        while i > 0 and buf[i - 1] in range(0x20, 0x7f):
            i -= 1
        run = buf[i:p].decode("ascii", "replace")
        # strip leading log-text noise up to the last 'struct ' boundary
        cut = run.rfind("struct ")
        if cut > 0:
            run = run[cut + len("struct "):]
            run = run.split(" ", 1)[-1] if " " in run else run
        fields = split_fields(run)
        log("=" * 72)
        log(f"### {target}   (declared {arity} elements)   "
            f"run {len(run)} chars -> {len(fields)} tokens")
        log("=" * 72)
        for k in range(0, len(fields), 4):
            log("    " + "  ".join(f"{f:34}" for f in fields[k:k + 4]))
        log("")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_structs_full.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:22000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
