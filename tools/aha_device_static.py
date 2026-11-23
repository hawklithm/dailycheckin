"""Read-only PE string xrefs and bounded disassembly; never loads the image."""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import struct

import capstone


class Image:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        pe = struct.unpack_from("<I", self.data, 0x3c)[0]
        if self.data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not PE")
        section_count = struct.unpack_from("<H", self.data, pe + 6)[0]
        optional_size = struct.unpack_from("<H", self.data, pe + 20)[0]
        optional = pe + 24
        if struct.unpack_from("<H", self.data, optional)[0] != 0x20b:
            raise ValueError("expected PE32+")
        self.base = struct.unpack_from("<Q", self.data, optional + 24)[0]
        self.sections = []
        for index in range(section_count):
            pos = optional + optional_size + index * 40
            name = self.data[pos:pos + 8].split(b"\0")[0].decode("ascii", errors="replace")
            virtual_size, rva, size, raw = struct.unpack_from("<IIII", self.data, pos + 8)
            self.sections.append((name, rva, raw, size, virtual_size))
        exception_rva, exception_size = struct.unpack_from("<II", self.data, optional + 112 + 3 * 8)
        offset = self.offset(exception_rva)
        self.functions = sorted(struct.unpack_from("<III", self.data, pos)
            for pos in range(offset, offset + exception_size - 11, 12))
        self.starts = [entry[0] for entry in self.functions]
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.md.detail = True

    def offset(self, rva):
        for name, start, raw, size, virtual in self.sections:
            if start <= rva < start + size:
                return raw + rva - start
        raise ValueError("RVA not file backed")

    def rva(self, offset):
        for name, start, raw, size, virtual in self.sections:
            if raw <= offset < raw + size:
                return start + offset - raw
        raise ValueError("offset not mapped")

    def function(self, rva):
        index = bisect.bisect_right(self.starts, rva) - 1
        if index >= 0:
            begin, end, unwind = self.functions[index]
            if begin <= rva < end:
                return begin, end
        return rva, rva + 0x100

    def literal(self, rva):
        try:
            pos = self.offset(rva)
        except ValueError:
            return ""
        raw = self.data[pos:pos + 220].split(b"\0", 1)[0]
        if len(raw) >= 3 and all(32 <= byte < 127 or byte in (9, 10, 13) for byte in raw):
            return raw.decode("ascii")
        return ""

    def dump(self, rva, output):
        begin, end = self.function(rva)
        index = bisect.bisect_right(self.starts, rva) - 1
        has_runtime_boundary = index >= 0 and self.functions[index][0] <= rva < self.functions[index][1]
        if end - begin > 0x10000:
            raise ValueError("bounded disassembly refuses a function over 64 KiB")
        pos = self.offset(begin)
        boundary = "PE runtime function" if has_runtime_boundary else "bounded window, no runtime function record"
        lines = [f"function RVA {begin:#x}..{end:#x}; image base {self.base:#x}; {boundary}"]
        for ins in self.md.disasm(self.data[pos:pos + end - begin], self.base + begin):
            notes = []
            for operand in ins.operands:
                if operand.type == capstone.x86_const.X86_OP_MEM and operand.mem.base == capstone.x86_const.X86_REG_RIP:
                    target = ins.address + ins.size + operand.mem.disp - self.base
                    text = self.literal(target)
                    notes.append(f"RIP->{target:#x}" + (f" {text!r}" if text else ""))
                elif ins.mnemonic in ("call", "jmp") and operand.type == capstone.x86_const.X86_OP_IMM:
                    notes.append(f"target RVA {operand.imm - self.base:#x}")
            lines.append(f"{ins.address - self.base:08x}: {ins.mnemonic:8s} {ins.op_str}" + (" ; " + "; ".join(notes) if notes else ""))
            if not has_runtime_boundary and ins.mnemonic == "ret":
                break
        path = output / f"function-{begin:08x}.asm"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"begin": hex(begin), "end": hex(end), "boundary": boundary, "path": str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--string", action="append", default=[])
    parser.add_argument("--rva", action="append", default=[])
    parser.add_argument("--caller", action="append", default=[], help="Find direct relative CALLs to an RVA")
    args = parser.parse_args()
    image = Image(args.image)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"kind": "static_pe_analysis", "image": str(args.image), "sha256": hashlib.sha256(image.data).hexdigest(),
              "image_base": hex(image.base), "strings": [], "functions": []}
    targets = set()
    for text in args.string:
        needle = text.encode("ascii")
        start = 0
        hits = []
        while True:
            found = image.data.find(needle, start)
            if found < 0:
                break
            root = image.data.rfind(b"\0", max(0, found - 200), found) + 1
            for position in set((root, found)):
                try:
                    rva = image.rva(position)
                except ValueError:
                    continue
                targets.add(rva)
                hits.append({"rva": hex(rva), "literal": image.literal(rva)})
            start = found + len(needle)
        report["strings"].append({"needle": text, "hits": hits})
    refs = []
    # Filter effective addresses before decoding; do not disassemble the whole
    # executable or follow candidate strings as instructions.
    pattern = re.compile(b"[\x40-\x4f][\x8d\x8b][\x05\x0d\x15\x1d\x25\x2d\x35\x3d].{4}", re.DOTALL)
    for name, code_rva, raw, size, virtual in image.sections:
        if name != ".text" or not targets:
            continue
        code = image.data[raw:raw + size]
        for match in pattern.finditer(code):
            target = code_rva + match.start() + 7 + struct.unpack_from("<i", match[0], 3)[0]
            if target not in targets:
                continue
            rva = code_rva + match.start()
            ins = next(image.md.disasm(code[match.start():match.start() + 15], image.base + rva, count=1), None)
            if ins is None or ins.size != 7:
                continue
            begin, end = image.function(rva)
            refs.append({"instruction": hex(rva), "function": hex(begin), "target": hex(target),
                         "literal": image.literal(target)})
    report["xrefs"] = refs
    caller_targets = {int(rva, 0) for rva in args.caller}
    callers = []
    if caller_targets:
        for name, code_rva, raw, size, virtual in image.sections:
            if name != ".text":
                continue
            code = image.data[raw:raw + size]
            for match in re.finditer(b"\xe8", code):
                pos = match.start()
                if pos + 5 > len(code):
                    continue
                target = code_rva + pos + 5 + struct.unpack_from("<i", code, pos + 1)[0]
                if target in caller_targets:
                    begin, end = image.function(code_rva + pos)
                    callers.append({"call_rva": hex(code_rva + pos), "target": hex(target), "function": hex(begin)})
    report["direct_call_candidates"] = callers
    functions = ({int(rva, 0) for rva in args.rva} | {int(ref["function"], 16) for ref in refs}
                 | {int(ref["function"], 16) for ref in callers})
    for rva in sorted(functions):
        report["functions"].append(image.dump(rva, args.output))
    (args.output / "index.json").write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
