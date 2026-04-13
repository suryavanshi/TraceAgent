from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from design_ir.models import BoardIR, Net, SchematicIR


RoutingClass = Literal["critical", "clocks", "power", "analog-sensitive", "general"]


@dataclass(frozen=True)
class RoutingPlanNet:
    net_name: str
    routing_class: RoutingClass
    autoroute_allowed: bool
    reason: str


@dataclass(frozen=True)
class RoutingPlan:
    nets: list[RoutingPlanNet]

    def summary(self) -> dict[str, int]:
        buckets = {"critical": 0, "clocks": 0, "power": 0, "analog-sensitive": 0, "general": 0}
        for entry in self.nets:
            buckets[entry.routing_class] += 1
        return buckets

    def autoroute_targets(self) -> list[str]:
        return [entry.net_name for entry in self.nets if entry.autoroute_allowed]


@dataclass(frozen=True)
class DsnExportResult:
    dsn_path: Path
    plan_path: Path


@dataclass(frozen=True)
class SessionImportResult:
    routed_nets: list[str]
    unrouted_nets: list[str]
    ses_path: Path


@dataclass(frozen=True)
class FreeroutingRunResult:
    status: Literal["completed", "failed"]
    dsn_path: Path
    ses_path: Path
    log_path: Path
    routed_nets: list[str]
    unrouted_nets: list[str]
    verification: dict


class RoutingPlanner:
    """Classifies nets and defines what autorouter is allowed to touch."""

    _CRITICAL_HINTS = ("USB_D", "ETH_", "PCIE", "MIPI", "DDR", "QSPI")
    _CLOCK_HINTS = ("CLK", "XTAL", "OSC", "MCO")
    _POWER_HINTS = ("GND", "VCC", "VBUS", "VIN", "VDD", "3V3", "5V", "1V8")
    _ANALOG_HINTS = ("ADC", "DAC", "SENSE", "REF", "ANALOG", "THERM", "AUDIO")

    def classify(self, schematic_ir: SchematicIR, board_ir: BoardIR) -> RoutingPlan:
        critical_from_intent = {intent.net_or_group.upper() for intent in board_ir.routing_intents if "critical" in intent.intent.lower()}
        plan_nets: list[RoutingPlanNet] = []
        for net in schematic_ir.nets:
            name = (net.name or net.net_id).upper()
            routing_class, reason = self._classify_name(name=name, net=net, critical_from_intent=critical_from_intent)
            plan_nets.append(
                RoutingPlanNet(
                    net_name=net.name or net.net_id,
                    routing_class=routing_class,
                    autoroute_allowed=routing_class not in {"critical", "clocks", "analog-sensitive"},
                    reason=reason,
                )
            )
        return RoutingPlan(nets=sorted(plan_nets, key=lambda item: item.net_name))

    def _classify_name(self, name: str, net: Net, critical_from_intent: set[str]) -> tuple[RoutingClass, str]:
        if name in critical_from_intent or any(token in name for token in self._CRITICAL_HINTS):
            return "critical", "matched critical intent/high-speed heuristic"
        if any(token in name for token in self._CLOCK_HINTS):
            return "clocks", "matched clock heuristic"
        if any(token in name for token in self._POWER_HINTS):
            return "power", "matched power rail heuristic"
        if any(token in name for token in self._ANALOG_HINTS):
            return "analog-sensitive", "matched analog-sensitivity heuristic"
        if len(net.nodes) >= 4:
            return "critical", "fanout heuristic promoted net to critical"
        return "general", "default classification"


class SpecctraSessionIO:
    """Adapter for DSN/SES handoff. Keeps planner output separate from routed artifacts."""

    def export_dsn(self, project_file: Path, pcb_file: Path, output_dir: Path, routing_plan: RoutingPlan) -> DsnExportResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        dsn_path = output_dir / f"{pcb_file.stem}.dsn"
        plan_path = output_dir / "routing_plan.json"
        plan_path.write_text(json.dumps({"nets": [entry.__dict__ for entry in routing_plan.nets]}, indent=2), encoding="utf-8")

        if not self._try_export_via_kicad_cli(pcb_file=pcb_file, dsn_path=dsn_path):
            # TODO: replace fallback with native KiCad DSN export adapter when available in all environments.
            dsn_path.write_text(
                "\n".join(
                    [
                        "# TraceAgent DSN fallback",
                        f"# source_project={project_file}",
                        f"# source_pcb={pcb_file}",
                        "# autoroute_targets=" + ",".join(routing_plan.autoroute_targets()),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

        return DsnExportResult(dsn_path=dsn_path, plan_path=plan_path)

    def import_ses(self, ses_path: Path, routing_plan: RoutingPlan) -> SessionImportResult:
        if not ses_path.exists():
            return SessionImportResult(routed_nets=[], unrouted_nets=[entry.net_name for entry in routing_plan.nets], ses_path=ses_path)

        routed_nets: list[str] = []
        for line in ses_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("route "):
                routed_nets.append(line.split(" ", 1)[1].strip())
        routed_set = set(routed_nets)
        all_nets = [entry.net_name for entry in routing_plan.nets]
        unrouted = [name for name in all_nets if name not in routed_set]
        return SessionImportResult(routed_nets=sorted(routed_set), unrouted_nets=unrouted, ses_path=ses_path)

    def _try_export_via_kicad_cli(self, pcb_file: Path, dsn_path: Path) -> bool:
        cmd = ["kicad-cli", "pcb", "export", "dsn", str(pcb_file), "--output", str(dsn_path)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False


class FreeroutingAdapter:
    def run_cli(self, dsn_path: Path, ses_path: Path, log_path: Path) -> bool:
        cmd = ["freerouting", "-de", str(dsn_path), "-do", str(ses_path)]
        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            log_path.write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
            return True
        except FileNotFoundError:
            log_path.write_text("freerouting executable not found\n", encoding="utf-8")
            return False
        except subprocess.CalledProcessError as exc:
            log_path.write_text((exc.stdout or "") + "\n" + (exc.stderr or ""), encoding="utf-8")
            return False


__all__ = [
    "DsnExportResult",
    "FreeroutingAdapter",
    "FreeroutingRunResult",
    "RoutingPlan",
    "RoutingPlanNet",
    "RoutingPlanner",
    "SessionImportResult",
    "SpecctraSessionIO",
]
