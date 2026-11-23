"""Find a method definition by name in aiServer_full.js and dump its body."""
import re
import sys

TEXT = open(r"D:\workspace\trae2api\notes\aiServer_full.js", encoding="utf-8", errors="replace").read()


def main() -> None:
    name = sys.argv[1]
    after = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    pats = [
        re.escape(name) + r'"\]\(',
        re.escape(name) + r"'\]\(",
        re.escape(name) + r'":function',
        re.escape(name) + r"':function",
        re.escape(name) + r"\(",
    ]
    for p in pats:
        for m in re.finditer(p, TEXT):
            i = m.start()
            seg = TEXT[i: i + after]
            if "function" not in seg[:80] and "(" not in seg[:40]:
                continue
            seg = re.sub(r"[^\x20-\x7e\n]", ".", seg)
            sys.stdout.buffer.write(seg.encode("ascii"))
            return
    print("no definition found")


if __name__ == "__main__":
    main()
