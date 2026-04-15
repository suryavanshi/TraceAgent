from __future__ import annotations

from pathlib import Path

from design_ir.models import BoardIR, BoardOutline, Net, SchematicIR
from worker.freerouting_job import run_freerouting_job


class StubFreerouting:
    def run_cli(self, dsn_path: Path, ses_path: Path, log_path: Path) -> bool:
        ses_path.write_text("route VBUS\n", encoding="utf-8")
        log_path.write_text(f"processed {dsn_path.name}\n", encoding="utf-8")
        return True


def test_freerouting_job_runs_and_verifies(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("worker.freerouting_job.run_kicad_erc", lambda _path: {"status": "completed", "issues": []})
    monkeypatch.setattr("worker.freerouting_job.run_kicad_drc", lambda _path: {"status": "completed", "issues": []})
    monkeypatch.setattr("worker.freerouting_job.run_manufacturability_checks", lambda _path: {"status": "completed", "issues": []})

    schematic = SchematicIR(nets=[Net(net_id="n1", name="VBUS"), Net(net_id="n2", name="USB_D_P")])
    board = BoardIR(board_outline=BoardOutline(shape="rectangle", dimensions_mm={"width": 10, "height": 10}))
    result = run_freerouting_job(
        project_file=str(tmp_path / "demo.kicad_pro"),
        pcb_file=str(tmp_path / "demo.kicad_pcb"),
        schematic_ir=schematic,
        board_ir=board,
        output_dir=str(tmp_path),
        freerouting=StubFreerouting(),
    )

    assert result.status == "completed"
    assert result.dsn_path.exists()
    assert result.log_path.exists()
    assert result.verification["status"] == "completed"
    assert "VBUS" in result.routed_nets
