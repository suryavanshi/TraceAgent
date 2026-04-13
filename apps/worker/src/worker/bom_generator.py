from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from design_ir.models import SchematicIR


@dataclass(frozen=True)
class BomRow:
    reference: str
    value: str
    footprint: str
    quantity: int
    primary_mpn: str
    alternate_mpns: str
    supplier_placeholder: str
    supplier_sku_placeholder: str
    notes: str


def _component_sort_key(component_ref: str) -> tuple[str, int]:
    prefix = "".join(ch for ch in component_ref if ch.isalpha())
    numeric = "".join(ch for ch in component_ref if ch.isdigit())
    return (prefix, int(numeric) if numeric else 0)


def generate_bom_csv(schematic_ir: SchematicIR) -> str:
    rows: dict[tuple[str, str, str, str, str], BomRow] = {}

    for component in sorted(schematic_ir.component_instances, key=lambda item: _component_sort_key(item.reference)):
        properties = component.properties or {}
        value = str(properties.get("value", component.value or component.symbol_id))
        footprint = str(properties.get("package", "UNKNOWN_PACKAGE"))
        mpn = str(properties.get("mpn", "UNASSIGNED_MPN"))
        alternate_values = properties.get("alternate_mpns", "")
        if isinstance(alternate_values, str):
            alternates = ";".join(sorted({item.strip() for item in alternate_values.split(";") if item.strip()}))
        else:
            alternates = ""
        notes = str(properties.get("bom_notes", ""))

        key = (value, footprint, mpn, alternates, notes)
        existing = rows.get(key)
        if existing is None:
            rows[key] = BomRow(
                reference=component.reference,
                value=value,
                footprint=footprint,
                quantity=1,
                primary_mpn=mpn,
                alternate_mpns=alternates,
                supplier_placeholder="TBD_SUPPLIER",
                supplier_sku_placeholder="TBD_SKU",
                notes=notes,
            )
            continue

        rows[key] = BomRow(
            reference=f"{existing.reference},{component.reference}",
            value=existing.value,
            footprint=existing.footprint,
            quantity=existing.quantity + 1,
            primary_mpn=existing.primary_mpn,
            alternate_mpns=existing.alternate_mpns,
            supplier_placeholder=existing.supplier_placeholder,
            supplier_sku_placeholder=existing.supplier_sku_placeholder,
            notes=existing.notes,
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "References",
            "Quantity",
            "Value",
            "Footprint",
            "Primary MPN",
            "Alternate MPNs",
            "Supplier",
            "Supplier SKU",
            "Notes",
        ]
    )
    for row in rows.values():
        writer.writerow(
            [
                row.reference,
                row.quantity,
                row.value,
                row.footprint,
                row.primary_mpn,
                row.alternate_mpns,
                row.supplier_placeholder,
                row.supplier_sku_placeholder,
                row.notes,
            ]
        )
    return output.getvalue()
