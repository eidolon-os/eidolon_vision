"""What ops/component.toml tells Ops, checked against this repository's own files.

Ops reads the contract instead of carrying a copy of these facts, so each claim
is held here to the unit file, the launcher and the code it describes.
"""

from __future__ import annotations

import os
import shlex
import tomllib
from pathlib import Path

from eidolon_vision.adapters.faces import opencv_zoo
from eidolon_vision.app.config import Settings
from eidolon_vision.app.faces_http import LOOPBACK_HOSTS

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = tomllib.loads((ROOT / "ops/component.toml").read_text(encoding="utf-8"))
UNIT = (ROOT / "deploy/systemd/eidolon-vision.service").read_text(encoding="utf-8")


def _unit_environment() -> dict[str, str]:
    return dict(
        assignment.split("=", 1)
        for line in UNIT.splitlines()
        if line.startswith("Environment=")
        for assignment in shlex.split(line.removeprefix("Environment="))
    )


def test_the_one_unit_runs_the_launcher_under_the_capability() -> None:
    [unit] = CONTRACT["units"]
    assert CONTRACT["component_id"] == "eidolon_vision"
    assert unit["id"] == "eidolon-vision" and unit["requires_capability"] == "local_face_identity"
    launcher = ROOT / unit["exec"]
    assert launcher.is_file() and os.access(launcher, os.X_OK)
    assert f"ExecStart=/opt/eidolon/current/eidolon_vision/{unit['exec']}\n" in UNIT
    assert f"User={unit['user']}\n" in UNIT
    assert "python -m eidolon_vision.app" in launcher.read_text(encoding="utf-8")


def test_the_declared_port_is_the_one_the_service_binds_on_loopback() -> None:
    [unit] = CONTRACT["units"]
    [role] = unit["serves"]
    port = CONTRACT["ports"][role]
    environment = _unit_environment()
    assert port["bind"] == "loopback" and environment["EIDOLON_VISION_HOST"] in LOOPBACK_HOSTS
    assert str(port["default"]) == environment["EIDOLON_VISION_PORT"] == str(Settings().port)


def test_the_unit_takes_no_credential_and_writes_only_its_declared_state() -> None:
    environment = _unit_environment()
    # Loopback and no token is what opens the face routes to the Host's own
    # services; a secret env file here would be a credential nobody issues.
    assert "inputs" not in CONTRACT
    assert not any("TOKEN" in name for name in environment)
    assert [line for line in UNIT.splitlines() if line.startswith("EnvironmentFile=")] == [
        "EnvironmentFile=/etc/eidolon/host.env"
    ]
    # The default would post facts to a Hub route that no longer exists.
    assert environment["EIDOLON_VISION_HUB_BASE_URL"] == ""
    audit = Path(environment["EIDOLON_VISION_AUDIT_LOG_PATH"])
    [reset] = CONTRACT["reset"]["factory"]
    assert audit.parent == Path(reset)
    assert f"StateDirectory={Path(reset).relative_to('/var/lib')}\n" in UNIT


def test_the_files_it_reads_from_the_models_artifact_are_the_ones_the_code_opens() -> None:
    [consumed] = CONTRACT["consumes"]
    assert (consumed["capability"], consumed["component"]) == ("local_face_identity", "eidolon_models")
    # bootstrap.build_face_service opens the policy beside the manifest; the
    # manifest names the two graphs, which the adapter checksums and loads.
    assert {opencv_zoo.MANIFEST, "face-policy.json"} <= set(consumed["files"])
    assert sum(name.endswith(".onnx") for name in consumed["files"]) == 2
    model_dir = _unit_environment()["EIDOLON_VISION_FACE_IDENTITY_MODEL_DIR"]
    assert Path(model_dir).parent == Path("/var/lib/eidolon/models")
