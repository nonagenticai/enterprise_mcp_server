import sys
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    failures = []
    inv = load_module("aa_feature_probe.inventory", HERE / "inventory.py")

    # 1. reserve_stock must exist
    if not hasattr(inv, "reserve_stock"):
        failures.append("aa_feature_probe.inventory.reserve_stock is not defined")
        print("FAIL:", "\n".join(failures))
        return 1

    # 2. negative qty raises ValueError
    try:
        inv.reserve_stock("WIDGET-1", -1)
    except ValueError:
        pass
    else:
        failures.append("reserve_stock did not raise ValueError on negative qty")

    # 3. successful reservation decrements stock and returns True
    before = inv.stock_level("WIDGET-1")
    ok = inv.reserve_stock("WIDGET-1", 3)
    after = inv.stock_level("WIDGET-1")
    if ok is not True:
        failures.append("reserve_stock returned %r, expected True" % (ok,))
    if after != before - 3:
        failures.append(
            "stock after reserve: %r, expected %r" % (after, before - 3)
        )

    # 4. insufficient stock leaves stock untouched and returns False
    before = inv.stock_level("WIDGET-2")
    ok = inv.reserve_stock("WIDGET-2", 1)
    after = inv.stock_level("WIDGET-2")
    if ok is not False:
        failures.append(
            "reserve_stock on insufficient stock returned %r, expected False"
            % (ok,)
        )
    if after != before:
        failures.append(
            "stock changed on failed reserve: %r, expected %r"
            % (after, before)
        )

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1

    print("OK: all acceptance checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
