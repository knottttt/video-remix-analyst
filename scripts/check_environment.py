from __future__ import annotations

import importlib.util
import shutil
import sys


REQUIRED_BINARIES = ["ffmpeg", "ffprobe"]
REQUIRED_MODULES = ["cv2", "numpy", "jinja2", "yaml", "openpyxl", "scenedetect"]
OPTIONAL_MODULES = ["librosa"]


def main() -> int:
    missing = []
    print("Binaries:")
    for name in REQUIRED_BINARIES:
        ok = shutil.which(name) is not None
        print(f"  {name}: {'ok' if ok else 'missing'}")
        if not ok:
            missing.append(name)

    print("\nPython modules:")
    for name in REQUIRED_MODULES:
        ok = importlib.util.find_spec(name) is not None
        print(f"  {name}: {'ok' if ok else 'missing'}")
        if not ok:
            missing.append(name)

    print("\nOptional modules:")
    for name in OPTIONAL_MODULES:
        ok = importlib.util.find_spec(name) is not None
        print(f"  {name}: {'ok' if ok else 'missing'}")

    if missing:
        print("\nMissing required dependencies detected.")
        return 1

    print("\nEnvironment check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
