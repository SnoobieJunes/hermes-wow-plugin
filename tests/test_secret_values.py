"""T-034 acceptance tests for secret values under a restriction (created 2026-11-11).

Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import copy
from pathlib import Path

from wow_addon_forge.apidocs import ApiIndex
from wow_addon_forge.check import check_addon
from wow_addon_forge.headless import World, minimal_api_index

REPO = Path(__file__).resolve().parent.parent


def _secret_index() -> ApiIndex:
    data = copy.deepcopy(minimal_api_index().data)
    data["entries"]["function"]["C_Probe.GetSecret"] = {
        "name": "C_Probe.GetSecret",
        "kind": "function",
        "namespace": "C_Probe",
        "system": None,
        "args": [],
        "returns": [{"type": "string"}],
        "flags": {},
        "c_api": True,
        "restricted": False,
        "secret": {"args": None, "returns": True, "conditions": []},
        "deprecated": False,
        "documented": True,
        "source": "test",
    }
    return ApiIndex(data)


def _write_addon(root: Path, body: str) -> Path:
    addon = root / "SecretProbe"
    addon.mkdir(parents=True)
    (addon / "SecretProbe.toc").write_text(
        "## Interface: 16001\n## Title: SecretProbe\n\nCore.lua\n",
        encoding="utf-8",
    )
    (addon / "Core.lua").write_text(body, encoding="utf-8")
    return addon


def test_secret_ops_are_findings_and_a_setter_is_not(tmp_path: Path) -> None:
    index = _secret_index()
    addon = _write_addon(
        tmp_path,
        "local secret = C_Probe.GetSecret()\n"
        "local frame = CreateFrame('Frame')\n"
        "frame:SetText(secret)\n"
        "local bad = secret + 1\n",
    )
    report = check_addon(addon, index=index, restriction="Combat")
    secrets = [item for item in report["findings"] if item["code"] == "secret-value"]
    assert secrets, report["findings"]
    assert secrets[0]["file"] == "Core.lua"
    assert secrets[0]["line"] == 4
    assert "arithmetic" in secrets[0]["message"]

    concat = _write_addon(
        tmp_path / "concat",
        "local secret = C_Probe.GetSecret()\nlocal bad = secret .. 'x'\n",
    )
    concat_report = check_addon(concat, index=index, restriction="Combat")
    assert any(
        item["code"] == "secret-value" and item["line"] == 2 for item in concat_report["findings"]
    )

    compared = _write_addon(
        tmp_path / "cmp",
        "local secret = C_Probe.GetSecret()\nlocal bad = secret < 1\n",
    )
    compared_report = check_addon(compared, index=index, restriction="Combat")
    compared_findings = compared_report["findings"]
    assert any(item["code"] == "secret-value" and item["line"] == 2 for item in compared_findings)

    open_world = World(index=index)
    client = open_world.client("Player", rank=0)
    client.load_addon(addon)
    assert client.eval("issecretvalue(C_Probe.GetSecret())") is False


def test_guildhall_and_forgeprobe_still_pass() -> None:
    index = minimal_api_index()
    for name in ("Guildhall", "ForgeProbe"):
        report = check_addon(REPO / "addons" / name, index=index)
        assert report["verdict"] == "pass", (name, report["findings"])
