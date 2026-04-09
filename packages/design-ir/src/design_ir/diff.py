from .models import DesignIR


def diff_design(old: DesignIR, new: DesignIR) -> dict[str, list[str]]:
    old_components = set(old.components)
    new_components = set(new.components)

    return {
        "added_components": sorted(new_components - old_components),
        "removed_components": sorted(old_components - new_components),
    }
