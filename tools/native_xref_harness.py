"""Targeted PE/Rust string xref helper for the installed Trae CN harness.dll.

This reads one PE image and reports references to an explicit, small set of
route strings. It never loads or executes the target DLL. It does not infer
Rust string lengths from neighboring strings: fat-string candidates require an
exact relocated VA pointer followed by the exact byte length.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import capstone
import lief


DEFAULT_TARGETS = [
    "/api/agent/v3/create_agent_task",
    "/api/agent/v3/commit_toolcall_result",
    "/api/agent/v3/llm_utils_chat",
    "/api/ide/v2/llm_raw_chat",
    "workflow/commit_toolcall",
]
RIP_MEMORY_OPS = (0x8D, 0x8B, 0x8A)
RIP_MODRM = (0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D)


def all_occurrences(haystack: bytes, needle: bytes):
    start = 0
    while True:
        found = haystack.find(needle, start)
        if found < 0:
            return
        yield found
        start = found + 1


def section_for_rva(binary, rva: int):
    for section in binary.sections:
        span = max(section.virtual_size, section.size)
        if section.virtual_address <= rva < section.virtual_address + span:
            return section
    return None


def rva_to_offset(binary, rva: int):
    section = section_for_rva(binary, rva)
    if section is None:
        return None
    delta = rva - section.virtual_address
    if delta >= section.size:
        return None
    return section.offset + delta


def offset_to_rva(binary, offset: int):
    for section in binary.sections:
        if section.offset <= offset < section.offset + section.size:
            return section.virtual_address + offset - section.offset
    return None


def runtime_functions(binary, image: bytes):
    pdata = next((s for s in binary.sections if s.name.rstrip("\x00") == ".pdata"), None)
    if pdata is None:
        return []
    result = []
    end = pdata.offset + pdata.size
    for pos in range(pdata.offset, end - 11, 12):
        begin, finish, unwind = struct.unpack_from("<III", image, pos)
        if begin and finish > begin and finish < binary.optional_header.sizeof_image:
            result.append((begin, finish, unwind))
    result.sort()
    return result


def containing_function(funcs, rva: int):
    # Number of .pdata records is modest; use binary search over sorted starts.
    lo, hi = 0, len(funcs)
    while lo < hi:
        mid = (lo + hi) // 2
        if funcs[mid][0] <= rva:
            lo = mid + 1
        else:
            hi = mid
    for index in range(max(0, lo - 2), min(len(funcs), lo + 1)):
        begin, end, unwind = funcs[index]
        if begin <= rva < end:
            return {"begin_rva": hex(begin), "end_rva": hex(end), "unwind_rva": hex(unwind)}
    return None


def exact_fat_strings(binary, image: bytes, string_rva: int, byte_length: int):
    pointer = struct.pack("<Q", binary.optional_header.imagebase + string_rva)
    length = struct.pack("<Q", byte_length)
    hits = []
    for section in binary.sections:
        name = section.name.rstrip("\x00")
        if name not in (".rdata", ".data"):
            continue
        start, end = section.offset, section.offset + section.size
        pos = start
        while True:
            pos = image.find(pointer, pos, end)
            if pos < 0:
                break
            after = pos + 8
            if after + 8 <= end and image[after:after + 8] == length:
                hits.append({
                    "file_offset": hex(pos),
                    "rva": hex(offset_to_rva(binary, pos)),
                    "section": name,
                    "pointer_rva": hex(string_rva),
                    "exact_len": byte_length,
                })
            pos += 1
    return hits


def candidate_rip_instructions(text: bytes, section, imagebase: int, targets: set[int]):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    code_rva = section.virtual_address
    code_raw = section.offset
    # Only inspect common LEA/MOV RIP-relative encodings. Capstone verifies
    # every candidate and its effective address before it is reported.
    patterns = []
    modrm_alt = b"(?:" + b"|".join(bytes([x]) for x in RIP_MODRM) + b")"
    for opcode in RIP_MEMORY_OPS:
        op = bytes([opcode])
        patterns.append(re.compile(b"[\\x40-\\x4f]" + op + modrm_alt + b".{4}", re.DOTALL))
        # Avoid decoding the opcode byte again as a second instruction when
        # the actual instruction starts one byte earlier with a REX prefix.
        patterns.append(re.compile(b"(?<![\\x40-\\x4f])" + op + modrm_alt + b".{4}", re.DOTALL))
    seen = set()
    refs = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            start = match.start()
            if start in seen:
                continue
            seen.add(start)
            instruction_bytes = text[start:start + 15]
            decoded = next(md.disasm(instruction_bytes, imagebase + code_rva + start, count=1), None)
            if decoded is None or decoded.id not in (capstone.x86_const.X86_INS_LEA,
                                                     capstone.x86_const.X86_INS_MOV):
                continue
            target = None
            for operand in decoded.operands:
                if operand.type == capstone.x86_const.X86_OP_MEM and operand.mem.base == capstone.x86_const.X86_REG_RIP:
                    target = decoded.address + decoded.size + operand.mem.disp
                    break
            if target is None:
                continue
            target_rva = target - imagebase
            if target_rva not in targets:
                continue
            rva = code_rva + start
            refs.append({
                "instruction_rva": hex(rva),
                "file_offset": hex(code_raw + start),
                "target_rva": hex(target_rva),
                "bytes": decoded.bytes.hex(" "),
                "asm": f"{decoded.mnemonic} {decoded.op_str}",
            })
    return refs


def function_calls(binary, image: bytes, funcs, function):
    begin = int(function["begin_rva"], 16)
    end = int(function["end_rva"], 16)
    if end - begin > 0x2000:
        return {"limited": True, "reason": "function range exceeds 0x2000 bytes"}
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    offset = rva_to_offset(binary, begin)
    if offset is None:
        return {"limited": True, "reason": "function start not file-backed"}
    code = image[offset:offset + (end - begin)]
    calls = []
    for ins in md.disasm(code, binary.optional_header.imagebase + begin):
        if ins.id == capstone.x86_const.X86_INS_CALL:
            target = None
            if ins.operands and ins.operands[0].type == capstone.x86_const.X86_OP_IMM:
                target = ins.operands[0].imm - binary.optional_header.imagebase
            calls.append({
                "call_rva": hex(ins.address - binary.optional_header.imagebase),
                "target_rva": hex(target) if target is not None else None,
                "target_function": containing_function(funcs, target) if target is not None else None,
            })
    return {"range_bytes": end - begin, "calls": calls}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dll", type=Path)
    parser.add_argument("--target", action="append", dest="targets")
    parser.add_argument("--candidate-rva", action="append", default=[],
                        help="Additional explicit data RVAs to test for RIP-relative code references")
    parser.add_argument("--candidate-range", action="append", default=[],
                        help="Inclusive RVA range START:END to test bytewise for nearby RIP-relative references")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    image = args.dll.read_bytes()
    digest = hashlib.sha256(image).hexdigest().upper()
    binary = lief.PE.parse(str(args.dll))
    if binary is None:
        raise SystemExit("LIEF could not parse PE")
    funcs = runtime_functions(binary, image)
    code_section = next((s for s in binary.sections if s.name.rstrip("\x00") == ".text"), None)
    if code_section is None:
        raise SystemExit("PE has no .text section")
    code = image[code_section.offset:code_section.offset + code_section.size]
    targets = args.targets or DEFAULT_TARGETS

    output = {
        "path": str(args.dll),
        "size": len(image),
        "sha256": digest,
        "imagebase": hex(binary.optional_header.imagebase),
        "sections": [{
            "name": s.name.rstrip("\x00"),
            "rva": hex(s.virtual_address),
            "raw_offset": hex(s.offset),
            "raw_size": hex(s.size),
        } for s in binary.sections],
        "targets": [],
        "limits": [
            "Only the explicitly supplied route literals and exact pointer+length pairs are searched.",
            "Code xrefs are limited to Capstone-validated RIP-relative LEA/MOV instructions.",
            "No code is executed and no function is fully disassembled outside xref-containing ranges.",
        ],
    }
    prepared = []
    all_rip_targets = set()
    for target in targets:
        needle = target.encode("utf-8")
        string_hits = []
        for file_offset in all_occurrences(image, needle):
            rva = offset_to_rva(binary, file_offset)
            if rva is None:
                continue
            sec = section_for_rva(binary, rva)
            string_hits.append({"file_offset": hex(file_offset), "rva": hex(rva),
                                "section": sec.name.rstrip("\x00") if sec else None})
        fat = []
        for hit in string_hits:
            fat.extend(exact_fat_strings(binary, image, int(hit["rva"], 16), len(needle)))
        rip_targets = {int(hit["rva"], 16) for hit in string_hits}
        rip_targets.update(int(entry["rva"], 16) for entry in fat)
        all_rip_targets.update(rip_targets)
        prepared.append({
            "literal": target,
            "literal_utf8_length": len(needle),
            "literal_occurrences": string_hits,
            "exact_fat_string_candidates": fat,
            "rip_targets": rip_targets,
        })

    extra_rvas = {int(value, 0) for value in args.candidate_rva}
    for value in args.candidate_range:
        start_text, end_text = value.split(":", 1)
        start_rva, end_rva = int(start_text, 0), int(end_text, 0)
        if end_rva < start_rva:
            raise SystemExit(f"invalid candidate range: {value}")
        extra_rvas.update(range(start_rva, end_rva + 1))
    all_rip_targets.update(extra_rvas)

    all_refs = candidate_rip_instructions(code, code_section, binary.optional_header.imagebase,
                                          all_rip_targets)
    for ref in all_refs:
        ref["containing_function"] = containing_function(funcs, int(ref["instruction_rva"], 16))
        if ref["containing_function"]:
            ref["function_calls"] = function_calls(binary, image, funcs, ref["containing_function"])
    for item in prepared:
        refs = [ref for ref in all_refs if int(ref["target_rva"], 16) in item["rip_targets"]]
        output["targets"].append({
            "literal": item["literal"],
            "literal_utf8_length": item["literal_utf8_length"],
            "literal_occurrences": item["literal_occurrences"],
            "exact_fat_string_candidates": item["exact_fat_string_candidates"],
            "rip_relative_code_refs": refs,
        })
    output["explicit_candidate_rva_code_refs"] = [
        {"candidate_rva": hex(rva), "references": [ref for ref in all_refs if int(ref["target_rva"], 16) == rva]}
        for rva in sorted(extra_rvas)
    ]
    rendered = json.dumps(output, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps({
            "sha256": digest,
            "size": len(image),
            "target_summary": [{
                "literal": item["literal"],
                "literal_occurrences": item["literal_occurrences"],
                "fat_string_candidates": item["exact_fat_string_candidates"],
                "code_refs": item["rip_relative_code_refs"],
            } for item in output["targets"]],
            "explicit_candidate_rva_code_refs": [entry for entry in output["explicit_candidate_rva_code_refs"]
                                                 if entry["references"]],
            "full_report": str(args.out),
        }, indent=2))
    else:
        print(rendered)


if __name__ == "__main__":
    main()
