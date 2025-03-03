import subprocess
import sys
from dataclasses import dataclass

from amaranth.lib.cdc import FFSynchronizer
from amaranth import *
from amaranth.lib.memory import MemoryData, Memory
from amaranth_boards.icebreaker import ICEBreakerPlatform
from amaranth.build import Resource, Pins, Attrs, Subsignal, DiffPairs
from amaranth_boards.resources import *

import rc

adc_ = Resource("adc", 0,
    Subsignal("ctrl",     Pins("2", dir="o", conn=("pmod", 0))),
    Subsignal("sense",    DiffPairs("1", "7", dir="i", conn=("pmod", 0)), Attrs(IO_STANDARD="SB_LVDS_INPUT"))
)
dac_ = Resource("dac", 0, Pins("1 2 3 4 7 8 9 10", dir="o", conn=("pmod", 1)), Attrs(IO_STANDARD="SB_LVCMOS"))
leds_ = LEDResources(pins={2: "1", 3: "2", 4: "3", 5: "4", 6: "7", 7: "8", 8: "9", 9: "10"}, conn=("pmod", 2),
                      attrs=Attrs(IO_STANDARD="SB_LVCMOS"))
debug_ = Resource("debug", 0,
    Subsignal("latched",     Pins("10", dir="o", conn=("pmod", 0))),
    Subsignal("sense",     Pins("4", dir="o", conn=("pmod", 0))),
    Subsignal("start",     Pins("9", dir="o", conn=("pmod", 0))),
)


@dataclass
class AdcParams:
    #: RC resistance.
    R: float
    #: RC capacitance.
    C: float
    #: I/O bank voltage used to charge RC circuit.
    Vdd: float
    #: Reference max voltage.
    Vref: float
    #: ADC resolution.
    res: int
    #: Linearizer LUT width.
    lut_width: int
    #: Clock speed of ADC.
    Hz: int


@dataclass
class SweepParams:
    #: I/O bank voltage used to charge power R2R DAC.
    Vdd: float
    #: Reference max voltage to charge to (must be <= Vdd).
    Vref: float
    #: Clock speed of DAC.
    clk_Hz: int
    #: Number of full sweeps (0 -> max -> 0) per second.
    sweep_Hz: int


sweep_rate_hz = 255


class DacSweep(Elaboratable):
    def __init__(self, params: SweepParams):
        self.peak_val = int(255 * (params.Vref / params.Vdd))
        self.clk_Hz = params.clk_Hz
        self.sweep_Hz = params.sweep_Hz

    def elaborate(self, plat):
        m = Module()
        plat.add_resources([dac_])

        dac = plat.request("dac")

        dac_cnt = Signal(range(int(self.clk_Hz // (2*self.sweep_Hz)) + 1))
        down = Signal(1)

        # DAC sweep code.
        with m.If(dac_cnt == int(self.clk_Hz // (2*self.sweep_Hz))):
            m.d.sync += [
                dac_cnt.eq(0)
            ]
            with m.If(down):
                m.d.sync += dac.o.eq(dac.o - 1)
            with m.Else():
                m.d.sync += dac.o.eq(dac.o + 1)

            with m.If(dac.o == 0):
                m.d.sync += [
                    down.eq(0),
                    dac.o.eq(dac.o + 1)
                ]
            # with m.If(dac.o == 255):
            with m.If(dac.o == self.peak_val):
                m.d.sync += [
                    down.eq(1),
                    dac.o.eq(dac.o - 1)
                ]
        with m.Else():
            m.d.sync += dac_cnt.eq(dac_cnt + 1)

        return m


class Top(Elaboratable):
    def __init__(self, params: AdcParams):
        self.rc = rc.RCCircuit(params.R, params.C, params.Vdd, params.Vref)
        self.lin = rc.AdcLinearizer(self.rc, params.res, params.lut_width,
                                    params.Hz)


    def elaborate(self, plat):
        m = Module()
        plat.add_resources([adc_, *leds_, debug_])

        leds = Cat(plat.request("led", i).o for i in range(2, 10))
        adc = plat.request("adc")
        # debug = plat.request("debug")

        up_cnt = Signal(range(self.lin.max_cnt + 1))
        # In theory, we can discharge the capacitor immediately by disabling
        # the output. However, this gives the ramp waveform a sawtooth-like
        # shape and all the harmonics that come with that. My experience is
        # that this makes the comparator stop working at 75% of full range.
        # Discharging slowly gives a triangle-like wave with better harmonics
        # (at the cost of having to wait).
        down_cnt = Signal(range(self.lin.discharge_cnt + 1))

        down = Signal(1)
        zero_run = Signal(4)
        latched_cnt = Signal(1)
        raw_val = Signal(self.lin.lut_width)

        sweep_params = SweepParams(self.rc.Vdd, self.rc.Vdd/2,
                                   self.lin.Hz, 255)
        sweep = DacSweep(sweep_params)

        latched_adc = Signal()
        # The comparator output (from the diff input) is very sensitive. Do not
        # load it more than necessary, and also try to block metastability.
        m.submodules += FFSynchronizer(adc.sense.i, latched_adc), sweep

        with m.If(down):
            m.d.sync += [
                down_cnt.eq(down_cnt + 1)
            ]

            with m.If(down_cnt == self.lin.discharge_cnt):
                # m.d.comb += leds[2].eq(1)
                m.d.sync += [
                    down_cnt.eq(0),
                    down.eq(0),
                    latched_cnt.eq(0),
                ]

        with m.Else():
            m.d.comb += adc.ctrl.o.eq(1)

            m.d.sync += [
                up_cnt.eq(up_cnt + 1),
            ]

            with m.If(adc.sense.i == 0):
                m.d.sync += zero_run.eq(zero_run + 1)
            with m.Else():
                m.d.sync += zero_run.eq(0)

            with m.If((zero_run == 2) & ~latched_cnt):
                m.d.sync += [
                    raw_val.eq(((up_cnt >> self.lin.clk_shift_amt) * self.lin.conv_factor) >> (self.lin.conv_precision)),
                    latched_cnt.eq(1)
                ]

            with m.If(up_cnt == self.lin.max_cnt):
                # m.d.comb += leds[1].eq(1)
                m.d.sync += [
                    up_cnt.eq(0),
                    down.eq(1),
                    zero_run.eq(0),
                ]
        # m.d.comb += leds.eq(raw_val)

        print(self.lin.lut_entries)
        mem_data = MemoryData(shape=self.lin.res, depth=2**self.lin.lut_width,
                              init=self.lin.lut_entries)
        mem = Memory(mem_data)
        r_port = mem.read_port()

        m.d.comb += [
            r_port.en.eq(1),
            r_port.addr.eq(raw_val)
        ]

        m.d.comb += leds.eq(r_port.data)
        m.submodules += mem

        # m.d.comb += [
        #     leds[4].eq(latched_cnt),
        #     leds[5].eq(latched_adc),
        #     leds[6].eq(down_cnt == ice_lin.discharge_cnt)
        # ]

        return m


if __name__ == "__main__":
    plat = ICEBreakerPlatform()

    # R = 1e5
    # C_ = 1e-9
    adc_params = AdcParams(R=0.996e5, C=0.893e-9, Vdd=3.3, Vref=(3.3/2), res=8,
                           Hz=12e6, lut_width=9)
    prod = plat.build(Top(adc_params), debug_verilog=True)

    with prod.extract("top.bin") as bitstream_filename:
        subprocess.check_call(["openFPGALoader", "-b", "ice40_generic", bitstream_filename])
