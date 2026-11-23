"""Print a decoded region around a marker from aiServer_full.js."""
import re
import sys

TEXT = open(r"D:\workspace\trae2api\notes\aiServer_full.js", encoding="utf-8", errors="replace").read()


def main() -> None:
    marker = sys.argv[1]
    before = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    after = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
    i = TEXT.find(marker)
    if i < 0:
        print(f"marker not found: {marker}")
        return
    seg = TEXT[max(0, i - before): i + after]
    seg = re.sub(r"[^\x20-\x7e\n]", ".", seg)
    sys.stdout.buffer.write(seg.encode("ascii"))


if __name__ == "__main__":
    main()
