"""Search decoded aiServer_full.js for a literal and print windows around all hits."""
import re
import sys

TEXT = open(r"D:\workspace\trae2api\notes\aiServer_full.js", encoding="utf-8", errors="replace").read()


def main() -> None:
    needle = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    before = int(sys.argv[3]) if len(sys.argv) > 3 else 250
    after = int(sys.argv[4]) if len(sys.argv) > 4 else 600
    start = 0
    shown = 0
    while shown < limit:
        i = TEXT.find(needle, start)
        if i < 0:
            break
        seg = TEXT[max(0, i - before): i + after]
        seg = re.sub(r"[^\x20-\x7e\n]", ".", seg)
        sys.stdout.buffer.write((f"----- hit {shown} at {i} -----\n{seg}\n\n").encode("ascii"))
        start = i + 1
        shown += 1
    if shown == 0:
        print("not found:", needle)


if __name__ == "__main__":
    main()
