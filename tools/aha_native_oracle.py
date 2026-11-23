"""Bounded offline oracle for selected functions of the pinned Aha PE image.

Runs original instructions inside Unicorn, never LoadLibrary or the client.
Only reviewed function ranges and small runtime substitutes may execute.
No OS imports, syscalls, networking, real caches or credentials are available.
Unicorn is a local analysis dependency, not a production dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "logs" / "aha-oracle-deps"))
from tools.aha_device_static import Image
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_PROT_ALL
from unicorn import x86_const as reg

EXPECTED_SHA256 = "eac5743ab3eafa528ae766a11a814cd0d8ea1c54cb948c66027e71479fe00ede"
STACK, HEAP, STOP = 0x1000000000, 0x1100000000, 0x1200000000
LIMIT = 4 * 1024 * 1024


class NativeOracle:
    def __init__(self, path: Path):
        self.image = Image(path)
        if hashlib.sha256(self.image.data).hexdigest() != EXPECTED_SHA256:
            raise ValueError("oracle only accepts the reviewed Trae CN 3.4.20 binary")
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        size = max(rva + max(size, virtual) for _, rva, _, size, virtual in self.image.sections)
        self.uc.mem_map(self.image.base, (size + 4095) & ~4095, UC_PROT_ALL)
        for _, rva, raw, size, _ in self.image.sections:
            self.uc.mem_write(self.image.base + rva, self.image.data[raw:raw + size])
        self.uc.mem_map(STACK, LIMIT, UC_PROT_ALL)
        self.uc.mem_map(HEAP, LIMIT * 8, UC_PROT_ALL)
        self.uc.mem_map(STOP, 4096, UC_PROT_ALL)
        self.ranges = []
        for rva in (0x41f5160, 0x2849050, 0x33588d0, 0x3358c70, 0x3999b90,
                    0x399a2d0, 0x3999cf0, 0x399a1c0, 0x399a480, 0x399a640,
                    0x3de3fb0, 0x3de44c0, 0x3de44f0, 0x3de4460, 0x3de4880, 0x53f4630,
                    0x4d59230, 0x2849440):
            begin, end = self.image.function(rva)
            self.ranges.append((self.image.base + begin, self.image.base + end))
        self.ranges.extend([(self.image.base + 0x3358bb0, self.image.base + 0x3358c6c),
                            (self.image.base + 0x284eafb, self.image.base + 0x284eb22),
                            (self.image.base + 0x284aa0c, self.image.base + 0x284aa5a)])
        self.hooks = {rva: name for rva, name in (
            (0x23bfb70, "malloc"), (0x23bf630, "free"), (0x5420460, "memcpy"),
            (0x5420b00, "memset"), (0x5420360, "memcmp"),
            (0x53e85e8, "time"), (0x53f460c, "srand"), (0x5408474, "tls"),
            (0x2844060, "region_manager"), (0x2844b90, "region_record"),
            (0x2849160, "telemetry_only"), (0x2849570, "telemetry_only"), (0x2849a70, "cache_observer"))}
        self.uc.hook_add(UC_HOOK_CODE, self._instruction)
        self.initial = self.uc.context_save()
        self.cursor = HEAP
        self.end = STOP
        self.clock = 1700000000
        self.region_ptr = 0
        self.cache_writes = 0
        self.tls_ptr = self.alloc(b"\0" * 256)

    def alloc(self, value: bytes | int) -> int:
        data = b"\0" * value if isinstance(value, int) else value
        if len(data) > LIMIT or self.cursor + max(32, len(data)) + 32 >= HEAP + LIMIT * 8:
            raise ValueError("oracle buffer limit")
        pos = self.cursor
        self.cursor += (max(32, len(data)) + 31) & ~15
        self.uc.mem_write(pos, data + b"\0" * 16)
        return pos

    def qword(self, pos: int) -> int:
        return struct.unpack("<Q", self.uc.mem_read(pos, 8))[0]

    def _return(self, result: int = 0):
        rsp = self.uc.reg_read(reg.UC_X86_REG_RSP)
        self.uc.reg_write(reg.UC_X86_REG_RAX, result & ((1 << 64) - 1))
        self.uc.reg_write(reg.UC_X86_REG_RIP, self.qword(rsp))
        self.uc.reg_write(reg.UC_X86_REG_RSP, rsp + 8)

    def _instruction(self, uc, address, size, user_data):
        if address == self.end:
            uc.emu_stop()
            return
        name = self.hooks.get(address - self.image.base)
        if name:
            a, b, c = (uc.reg_read(r) for r in (reg.UC_X86_REG_RCX, reg.UC_X86_REG_RDX, reg.UC_X86_REG_R8))
            if name == "malloc":
                self._return(self.alloc(a))
            elif name in ("memcpy", "memset", "memcmp"):
                if c > LIMIT:
                    raise ValueError("oracle runtime length limit")
                if name == "memcpy":
                    uc.mem_write(a, bytes(uc.mem_read(b, c)))
                    self._return(a)
                elif name == "memset":
                    uc.mem_write(a, bytes([b & 255]) * c)
                    self._return(a)
                else:
                    left, right = bytes(uc.mem_read(a, c)), bytes(uc.mem_read(b, c))
                    self._return((left > right) - (left < right))
            elif name == "time":
                self._return(self.clock)
            elif name == "srand":
                uc.mem_write(self.tls_ptr + 0x28, struct.pack("<I", a & 0xffffffff))
                self._return()
            elif name == "tls":
                self._return(self.tls_ptr)
            elif name == "region_manager":
                self._return(HEAP)
            elif name == "region_record":
                self._return(self.region_ptr)
            elif name == "cache_observer":
                self.cache_writes += 1
                self._return()
            else:
                self._return()
            return
        if not any(start <= address < end for start, end in self.ranges):
            raise ValueError(f"unreviewed execution blocked at RVA {address - self.image.base:#x}")

    def call(self, rva: int, *args: int, stop: int = STOP, registers: dict | None = None):
        self.uc.context_restore(self.initial)
        rsp = STACK + LIMIT - 0x108
        self.uc.mem_write(rsp, struct.pack("<Q", STOP) + b"\0" * 96)
        self.uc.reg_write(reg.UC_X86_REG_RSP, rsp)
        for target, value in zip((reg.UC_X86_REG_RCX, reg.UC_X86_REG_RDX, reg.UC_X86_REG_R8, reg.UC_X86_REG_R9), args):
            self.uc.reg_write(target, value)
        for n, value in enumerate(args[4:]):
            self.uc.mem_write(rsp + 0x28 + n * 8, struct.pack("<Q", value))
        for target, value in (registers or {}).items():
            self.uc.reg_write(target, value)
        self.end = stop
        self.uc.emu_start(self.image.base + rva, stop, timeout=5_000_000, count=2_000_000)
        if self.uc.reg_read(reg.UC_X86_REG_RIP) != stop:
            raise ValueError("oracle did not reach the reviewed return boundary")
        return self.uc.reg_read(reg.UC_X86_REG_RAX)

    def uint64(self, value: str) -> dict:
        raw = value.encode("utf-8")
        view = self.alloc(struct.pack("<QQ", self.alloc(raw), len(raw)))
        output = self.alloc(8)
        ok = bool(self.call(0x41f5160, view, output) & 255)
        return {"input": value, "ok": ok, "value": self.qword(output)}

    def string(self, value: str) -> bytes:
        data = value.encode()
        if len(data) <= 22:
            return bytes([len(data) * 2]) + data + b"\0" * (23 - len(data))
        return struct.pack("<QQQ", 1, len(data), self.alloc(data))

    def needs_registration(self, device_id: str, region: str, region_record_ready: bool) -> bool:
        service = bytearray(0x200)
        service[0x10:0x28] = self.string(device_id)
        service[0xa0:0xb8] = self.string(region)
        record = bytearray(0x90)
        record[0x80] = region_record_ready
        self.region_ptr = self.alloc(bytes(record))
        return bool(self.call(0x2849050, self.alloc(bytes(service))) & 255)

    def retry_delay(self, attempt: int) -> int:
        self.call(0x284eafb, stop=self.image.base + 0x284eb22,
                  registers={reg.UC_X86_REG_EDI: attempt & 0xffffffff})
        return self.uc.reg_read(reg.UC_X86_REG_EBP)

    def header_number(self, value: str) -> float:
        service = bytearray(0x100)
        service[0x10:0x28] = self.string(value)
        self.call(0x284aa0c, stop=self.image.base + 0x284aa5a,
                  registers={reg.UC_X86_REG_RDI: self.alloc(bytes(service)),
                             reg.UC_X86_REG_RSP: STACK + LIMIT - 0x1000})
        return struct.unpack("<d", struct.pack("<Q", self.uc.reg_read(reg.UC_X86_REG_XMM2) & ((1 << 64) - 1)))[0]

    def base64(self, value: str) -> dict:
        raw = value.encode()
        output = self.alloc(len(raw) + 32)
        length = self.call(0x4d59230, output, self.alloc(raw), len(raw), 0)
        ok = length != (1 << 64) - 1
        return {"input": value, "ok": ok,
                "decoded_hex": bytes(self.uc.mem_read(output, length)).hex() if ok else ""}

    def read_string(self, ptr: int) -> str:
        first = self.uc.mem_read(ptr, 1)[0]
        length = self.qword(ptr + 8) if first & 1 else first >> 1
        source = self.qword(ptr + 16) if first & 1 else ptr + 1
        return bytes(self.uc.mem_read(source, length)).decode()

    def migrate(self, current: str, old: str) -> dict:
        service = bytearray(0x300)
        service[0x10:0x28] = self.string(current)
        ptr = self.alloc(bytes(service))
        self.cache_writes = 0
        accepted = bool(self.call(0x2849440, ptr, self.alloc(self.string(old))) & 255)
        return {"current": current, "old": old, "accepted": accepted,
                "device_id": self.read_string(ptr + 0x10),
                "old_device_id": self.read_string(ptr + 0x58), "write_cache": bool(self.cache_writes)}

    def encrypt(self, value: bytes) -> bytes:
        output, length = self.alloc(len(value) + 256), self.alloc(struct.pack("<Q", len(value) + 256))
        self.call(0x33588d0, self.alloc(value), len(value), output, length)
        return bytes(self.uc.mem_read(output, self.qword(length)))

    def decrypt(self, value: bytes) -> bytes:
        output, length = self.alloc(len(value) + 256), self.alloc(struct.pack("<Q", len(value) + 256))
        self.call(0x3358c70, self.alloc(value), len(value), output, length)
        return bytes(self.uc.mem_read(output, self.qword(length)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--codec", action="store_true")
    args = parser.parse_args()
    oracle = NativeOracle(args.image)
    values = ["", "0", "00", "1", "+1", "+0", "-1", " 1", "\t1", "1 ", "1x", "１２", "١", "18446744073709551615", "18446744073709551616", "99999999999999999999999"]
    rng = random.Random(4226)
    values += [str(rng.randrange(1 << 66)) for _ in range(80)]
    numbers = [oracle.uint64(value) for value in values]
    policies = [{"device_id": did, "region": region, "region_record_ready": ready,
                 "needs_registration": oracle.needs_registration(did, region, ready)}
                for did in ("1", "0", "+1", "", " 1", "18446744073709551616")
                for region in ("CN", "cn", "CNx", "SG", "") for ready in (False, True)]
    retries = [{"attempt": n, "delay_ms": oracle.retry_delay(n)}
               for n in [*range(12), 24, 25, 144, 145, 149, 150, 10000, 21474836, 21474837, 4294967295]]
    result = {"source_sha256": EXPECTED_SHA256, "oracle": "Unicorn 2.1.4, allowlisted original instructions",
              "host_native_client_started": False, "live_service_calls": False,
              "uint64": numbers, "startup_policy": policies, "retry_delay": retries}
    result["base64"] = [oracle.base64(value) for value in ("", "Zg==", "Zh==", "Zg", "Zg=", "Zg===",
        " Zg==", "Zg==\n", "====", "AAAA", "AA==AAAA", "A===", "A", "Zm9v", "Zm9v=", "Zm9v====", "_w==", "/w==", "１２")]
    result["migration"] = [oracle.migrate(current, old) for current in ("", "0", "123", "456", "+1")
                           for old in ("", "0", "123", "456", "abc", "+1", "18446744073709551615", " 1")]
    result["header_number"] = [{"input": value, "double": oracle.header_number(value)} for value in values]
    if args.codec:
        result["codec"] = []
        for size in (0, 1, 15, 16, 17, 31, 32, 64, 65, 255, 1024):
            plain = bytes(n % 251 for n in range(size))
            encrypted = oracle.encrypt(plain)
            decoded = oracle.decrypt(encrypted)
            if decoded != plain:
                raise ValueError(f"native emulated codec roundtrip failed for size {size}")
            result["codec"].append({"plaintext_hex": plain.hex(), "clock": oracle.clock,
                                    "encrypted_hex": encrypted.hex(), "decrypted_hex": decoded.hex()})
        for clock in (0, 1, 1700000001, 4294967296, -1):
            oracle.clock = clock
            plain = b"offline-clock-fixture"
            encrypted = oracle.encrypt(plain)
            decoded = oracle.decrypt(encrypted)
            if decoded != plain:
                raise ValueError("native clock codec roundtrip failed")
            result["codec"].append({"plaintext_hex": plain.hex(), "clock": clock,
                                    "encrypted_hex": encrypted.hex(), "decrypted_hex": decoded.hex()})
        # Crafted inputs exercise the ORIGINAL decoder, not a Python roundtrip.
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from trae2api.aha_cache_codec import _key_iv, LEGACY_HEADER
        raw = oracle.encrypt(b"x")
        seed = raw[6:38]
        digest_plain = hashlib.sha512(b"x").digest() + b"x"
        def frame(legacy=False, bad_padding=False, bad_digest=False):
            plain = bytearray(digest_plain + bytes([15]) * 15)
            if bad_padding:
                plain[-2] = 0
            if bad_digest:
                plain[0] ^= 1
            key, iv = _key_iv(seed, legacy)
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
            return (LEGACY_HEADER if legacy else raw[:6]) + seed + cipher.update(bytes(plain)) + cipher.finalize()
        result["codec_decryption"] = []
        for name, data, expected in (("legacy", frame(legacy=True), b"x"),
                ("nonuniform_padding", frame(bad_padding=True), b"x"),
                ("digest_mismatch", frame(bad_digest=True), b""),
                ("invalid_header", b"x" + raw[1:], b"")):
            decoded = oracle.decrypt(data)
            if decoded != expected:
                raise ValueError(f"native decoder case {name} disagreed")
            result["codec_decryption"].append({"name": name, "encrypted_hex": data.hex(), "decoded_hex": decoded.hex()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: len(value) for key, value in result.items() if isinstance(value, list)}))


if __name__ == "__main__":
    main()
