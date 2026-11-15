"""Bundle-local checks; Core's public CLI owns runtime/descriptor validation."""

import hashlib
from pathlib import Path

import yaml


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "extension.yaml").read_text())
    descriptor = yaml.safe_load((root / "extension-descriptor.yaml").read_text())
    assert manifest["extension_id"] == descriptor["extension_id"] == "flowsteward.x"
    assert manifest["version"] == descriptor["release_version"] == "1.0.0"
    for row in manifest["python_requirements"]:
        wheels = list((root / "wheels").glob(row["name"].replace("-", "_") + "-*.whl"))
        assert wheels, row["name"]
        for wheel in wheels:
            assert "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest() in row["hashes"]
    assert (root / "icon.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert "icon.png SHA-256" in (root / "BRANDING.md").read_text()
    print("X bundle-local contracts and pinned wheels verified.")


if __name__ == "__main__":
    main()
