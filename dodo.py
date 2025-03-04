"""Task driver for rc-adc."""

from doit.task import clean_targets
from doit.tools import run_once


# YoWASP
def write_yowasp_env_toolchain(fn):  # noqa: D103
    envs = {
        "AMARANTH_USE_YOSYS": "builtin",
        "YOSYS": "yowasp-yosys",
        "NEXTPNR_ICE40": "yowasp-nextpnr-ice40",
        "ICEPACK": "yowasp-icepack"
    }

    with open(fn, "w") as fp:
        for k, v in envs.items():
            fp.write(f"{k}={v}\n")


def task_prepare_yowasp():
    """prepare rc-adc source for YoWASP tools"""
    return {
        "actions": [(write_yowasp_env_toolchain, (".env.toolchain",))],
        "uptodate": [run_once],
        "clean": [clean_targets],
        "targets": [".env.toolchain"],
    }
