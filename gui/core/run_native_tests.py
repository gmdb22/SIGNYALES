"""
Compiles and runs the native packet.h / frame.h tests with g++, on any OS.

Same tests as firmware/tests/native/run_all.sh, which needs bash and so
can't run in PowerShell. Build output goes to a temporary folder, not the
repo. Exit code 0 only if both tests compile and pass.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[2] / "firmware" / "tests" / "native"
TESTS = [
    ("test_packet_logic.cpp", NATIVE.parent.parent / "glove" / "src"),
    ("test_frame_logic.cpp", NATIVE.parent.parent / "receiver" / "src"),
]


def main() -> int:
    gpp = shutil.which("g++")
    if not gpp:
        print("SKIPPED: g++ not found. Install a C++ compiler (e.g. MSYS2/MinGW on Windows), "
              "or rely on the CI job, which runs these tests on every push.")
        return 2
    ok = True
    with tempfile.TemporaryDirectory(prefix="signyales_native_") as tmp:
        for src, inc in TESTS:
            exe = Path(tmp) / (Path(src).stem + (".exe" if sys.platform == "win32" else ""))
            print(f"--- compiling {src}")
            c = subprocess.run([gpp, "-Wall", "-Wextra", f"-I{inc}", "-o", str(exe),
                                str(NATIVE / src)], capture_output=True, text=True)
            print(c.stdout + c.stderr, end="")
            if c.returncode != 0:
                print(f"FAIL: {src} did not compile")
                ok = False
                continue
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            print(r.stdout + r.stderr, end="")
            ok = ok and r.returncode == 0
    print("ALL NATIVE LOGIC TESTS PASSED" if ok else "NATIVE LOGIC TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
