"""Decode the remaining _0xHEX(0xNNNN) string references in a region using the
known rotation from the main string array."""
import json
import re
import sys

strings_file = r"D:\workspace\trae2api\notes\strings_aiServer.json"


def load_array():
    data = json.load(open(strings_file, encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    raise SystemExit("unexpected strings json shape")


def main() -> None:
    arr = load_array()
    print("array len:", len(arr), file=sys.stderr)
    # The decoder is: arr[(idx + ROT) % len]; find ROT by locating a known literal
    # We know from analysis: 0x1a0f -> 'builderWithMcp' style; try all rotations
    # against a set of known (hex -> expected) pairs harvested earlier:
    pairs = [(0x1a0f, "BuilderWithMcp"), (0x1a0f, "builderWithMcp"),
             (0x8326, "SOLO"), (0x67a2, "SOLO")]
    for idx, expected in pairs:
        for rot in range(len(arr)):
            if arr[(idx + rot) % len(arr)] == expected:
                print(f"ROTATION={rot} (idx {hex(idx)} -> {expected})", file=sys.stderr)
                return rot
    print("rotation not found via known pairs", file=sys.stderr)
    return None


if __name__ == "__main__":
    main()
