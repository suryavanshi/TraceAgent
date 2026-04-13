from pathlib import Path

from design_ir.models import BoardIR, BoardOutline, ComponentInstance, Footprint, Net, SchematicIR, StackupLayer, Symbol

from worker.release import build_release_bundle


def _schematic() -> SchematicIR:
    return SchematicIR(
        symbols=[Symbol(symbol_id="sym_u", kind="mcu")],
        component_instances=[
            ComponentInstance(
                instance_id="u1",
                symbol_id="sym_u",
                reference="U1",
                properties={"value": "MCU", "package": "QFN32", "mpn": "ABC123", "alternate_mpns": "DEF456"},
            )
        ],
        nets=[Net(net_id="n1", name="GND")],
    )


def _board() -> BoardIR:
    return BoardIR(
        board_outline=BoardOutline(shape="rectangle", dimensions_mm={"width": 40, "height": 30}),
        stackup=[StackupLayer(name="F.Cu", kind="copper", thickness_um=35)],
        footprints=[Footprint(footprint_id="fp_u1", instance_id="u1", library_ref="Package_QFN:QFN-32", package="QFN32", placement={"x_mm": 10, "y_mm": 12, "rotation_deg": 90})],
        mounting_holes=[],
        fixed_edge_connectors=[],
        placement_constraints=[],
        design_rules=[],
        net_classes=[],
        keepouts=[],
        zones=[],
        routing_intents=[],
    )


def test_build_release_bundle_writes_manifest_and_required_outputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("worker.release.run_kicad_erc", lambda _path: {"status": "completed", "tool": "kicad-erc", "issues": []})
    monkeypatch.setattr("worker.release.run_kicad_drc", lambda _path: {"status": "completed", "tool": "kicad-drc", "issues": []})

    result = build_release_bundle(
        project_name="sensor-board",
        version="v1.2.3",
        snapshot_id="snap-123",
        snapshot_git_commit_hash="abcdef1234567890",
        schematic_ir=_schematic(),
        board_ir=_board(),
        output_root=tmp_path,
    )

    manifest_path = Path(result.files["manifest"])
    assert manifest_path.exists()
    manifest = result.manifest
    assert manifest["snapshot"]["snapshot_id"] == "snap-123"
    assert manifest["snapshot"]["git_commit_hash"] == "abcdef1234567890"
    assert any(item["path"] == "bom/bom.csv" for item in manifest["contents"])
    assert (result.output_dir / "assembly" / "pick_and_place.csv").exists()
    assert (result.output_dir / "reports" / "erc.json").exists()
