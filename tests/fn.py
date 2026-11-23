"""Find and print a function/method body in aiServer_full.js by name."""
import re
import sys

TEXT = open(r"D:\workspace\trae2api\notes\aiServer_full.js", encoding="utf-8", errors="replace").read()


def main() -> None:
    name = sys.argv[1]
    # match:  "name"]( ... ){   or  ['name']( ... ){   or  name(...){
    pats = [
        rf'"{re.escape(name)}"\]\(_0x[0-9a-fA-F]+,?\s*_0x[0-9a-fA-F]*\)\s*\{{',
        rf"'{re.escape(name)}'\]\([^)]*\)\s*\{{",
        rf'\["{re.escape(name)}"\]\(',
        rf'\[{re.escape(name)}\]\(',
    ]
    for p in pats:
        m = re.search(p, TEXT)
        if m:
            i = m.start()
            seg = TEXT[i: i + int(sys.argv[2] if len(sys.argv) > 2 else 1800)]
            seg = re.sub(r"[^\x20-\x7e\n]", ".", seg)
            sys.stdout.buffer.write(seg.encode("ascii"))
            return
    print(f"definition not found for {name}")


if __name__ == "__main__":
    main()
