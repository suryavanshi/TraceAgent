from design_ir.models import ComponentInstance, Net, SchematicIR, Symbol

from worker.bom_generator import generate_bom_csv


def test_generate_bom_includes_alternates_and_sourcing_columns() -> None:
    schematic = SchematicIR(
        symbols=[Symbol(symbol_id="sym_r", kind="resistor")],
        component_instances=[
            ComponentInstance(
                instance_id="r1",
                symbol_id="sym_r",
                reference="R1",
                properties={
                    "value": "10k",
                    "package": "0402",
                    "mpn": "RC0402FR-0710KL",
                    "alternate_mpns": "ERJ-2RKF1002X;CRCW040210K0FKED",
                },
            ),
            ComponentInstance(
                instance_id="r2",
                symbol_id="sym_r",
                reference="R2",
                properties={
                    "value": "10k",
                    "package": "0402",
                    "mpn": "RC0402FR-0710KL",
                    "alternate_mpns": "ERJ-2RKF1002X;CRCW040210K0FKED",
                },
            ),
        ],
        nets=[Net(net_id="n1", name="GND")],
    )

    csv_output = generate_bom_csv(schematic)

    assert "Alternate MPNs" in csv_output
    assert "TBD_SUPPLIER" in csv_output
    assert "R1,R2" in csv_output
    assert ",2,10k,0402,RC0402FR-0710KL," in csv_output
