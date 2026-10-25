"""Decode remaining obfuscated string references in a file.

Decoder solved from the plugin's own string array:
    value = STRINGS[(idx + ROT) % len(STRINGS)]   with ROT = 15992
Usage: python tests/decode_refs.py <file> <out_file>
"""
import json
import re
import sys

STRINGS_FILE = r"D:\workspace\trae2api\notes\strings_aiServer.json"
ROT = 15992

STRINGS = json.load(open(STRINGS_FILE, encoding="utf-8"))
N = len(STRINGS)

REF = re.compile(r"_0x[0-9a-fA-F]{4,6}\(0x([0-9a-fA-F]{3,6})\)")


def decode_file(src: str, dst: str) -> int:
    text = open(src, encoding="utf-8", errors="replace").read()
    count = 0

    def repl(m: "re.Match[str]") -> str:
        nonlocal count
        idx = int(m.group(1), 16)
        if idx >= N:
            return m.group(0)
        count += 1
        val = STRINGS[(idx + ROT) % N]
        return json.dumps(val, ensure_ascii=False)

    out = REF.sub(repl, text)
    open(dst, "w", encoding="utf-8").write(out)
    return count


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    n = decode_file(src, dst)
    print(f"decoded {n} references -> {dst}")
