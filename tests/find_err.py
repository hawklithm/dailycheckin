"""Find the traceback that mentions NameError in the server stderr log."""
import re
import sys

LOG = r"D:\workspace\trae2api\notes\server-err.log"
text = open(LOG, encoding="utf-8", errors="replace").read()
# print the last traceback block(s) that reference our code
blocks = re.split(r"(?=Traceback \(most recent call last\):)", text)
shown = 0
for b in reversed(blocks):
    if "trae2api" in b or "NameError" in b:
        sys.stdout.buffer.write(b[-2500:].encode("utf-8"))
        sys.stdout.buffer.write(b"\n" + b"=" * 70 + b"\n")
        shown += 1
        if shown >= 3:
            break
if shown == 0:
    print("no traceback found")
