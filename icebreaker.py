import subprocess
import sys
from amaranth.lib.cdc import FFSynchronizer
from amaranth import *
from amaranth.lib.memory import MemoryData, Memory
from amaranth_boards.icebreaker import ICEBreakerPlatform
from amaranth.build import Resource, Pins, Attrs, Subsignal, DiffPairs
from amaranth_boards.resources import *

import rc

R = 0.996e5
# R = 1e5
C_ = 0.893e-9
# C_ = 1e-9

RC = R*C_
Vin = 3.3
Vmax = (3.3/2)
res = 8
Hz = 12e6
lut_width = 9


adc_ = Resource("adc", 0,
    Subsignal("ctrl",     Pins("2", dir="o", conn=("pmod", 0))),
    Subsignal("sense",    DiffPairs("1", "7", dir="i", conn=("pmod", 0)), Attrs(IO_STANDARD="SB_LVDS_INPUT"))
)
dac_ = Resource("dac", 0, Pins("1 2 3 4 7 8 9 10", dir="o", conn=("pmod", 1)), Attrs(IO_STANDARD="SB_LVCMOS"))
leds_ = LEDResources(pins={2: "1", 3: "2", 4: "3", 5: "4", 6: "7", 7: "8", 8: "9", 9: "10"}, conn=("pmod", 2),
                      attrs=Attrs(IO_STANDARD="SB_LVCMOS"))

ice_rc = rc.RCCircuit(R=R, C=C_, Vdd=Vin, Vref=Vmax)
ice_lin = rc.AdcLinearizer(ice_rc, res=res, lut_width=lut_width, Hz=Hz)

class Top(Elaboratable):
    def elaborate(self, plat):
        m = Module()
        plat.add_resources([adc_, dac_, *leds_])

        leds = Cat(plat.request("led", i).o for i in range(2, 10))
        dac = plat.request("dac")
        adc = plat.request("adc")

        up_cnt = Signal(range(ice_lin.max_cnt + 1))
        # In theory, we can discharge the capacitor immediately by disabling
        # the output. However, this gives the ramp waveform a sawtooth-like
        # shape and all the harmonics that come with that. My experience is
        # that this makes the comparator stop working at 75% of full range.
        # Discharging slowly gives a triangle-like wave with better harmonics
        # (at the cost of having to wait).
        down_cnt = Signal(range(ice_lin.discharge_cnt + 1))

        down = Signal(1)
        zero_run = Signal(4)
        latch_cnt = Signal(1)
        do_mul = Signal(1)
        raw_val = Signal(lut_width)
        mul_done = Signal()

        m.d.comb += leds[3].eq(~latch_cnt)

        latched_adc = Signal()
        # The comparator output (from the diff input) is very sensitive. Do not
        # load it more than necessary, and also try to block metastability.
        m.submodules += FFSynchronizer(adc.sense.i, latched_adc)
        m.d.comb += leds[0].eq(latched_adc)

        with m.If(down):
            m.d.sync += [
                down_cnt.eq(down_cnt + 1)
            ]

            with m.If(down_cnt == ice_lin.discharge_cnt):
                m.d.comb += leds[2].eq(1)
                m.d.sync += [
                    down_cnt.eq(0),
                    down.eq(0),
                    latch_cnt.eq(0),
                    mul_done.eq(0),
                    do_mul.eq(0)
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

            with m.If(zero_run == 2):
                m.d.sync += [
                    latch_cnt.eq(1),
                    do_mul.eq(1)
                ]

            with m.If(up_cnt == ice_lin.max_cnt):
                m.d.comb += leds[1].eq(1)
                m.d.sync += [
                    up_cnt.eq(0),
                    down.eq(1),
                    zero_run.eq(0),
                ]

        with m.If(do_mul & ~mul_done):
            m.d.sync += [
                # Minus one to simulate that we latched last cycle.
                raw_val.eq((((up_cnt - 1) >> ice_lin.clk_shift_amt) * ice_lin.conv_factor) >> (ice_lin.conv_precision)),
                mul_done.eq(1),
                do_mul.eq(0)
            ]

        # m.d.comb += dac.o.eq(raw_val)

        # print(ice_lin.lut_entries)
        mem_data = MemoryData(shape=res, depth=2**ice_lin.lut_width, init=ice_lin.lut_entries)
        mem = Memory(mem_data)
        r_port = mem.read_port()

        m.d.comb += [
            r_port.en.eq(1),
            r_port.addr.eq(raw_val)
        ]

        # m.d.comb += dac.o.eq(r_port.data)
        # m.submodules += mem

        # DAC sweep code.
        # with m.If(dac_cnt == (12000000 // sweep_rate_hz)):
        #     m.d.sync += [
        #         dac_cnt.eq(0)
        #     ]
        #     with m.If(down):
        #         m.d.sync += dac.o.eq(dac.o - 1)
        #     with m.Else():
        #         m.d.sync += dac.o.eq(dac.o + 1)

        #     with m.If(down_cnt == ):
        #         m.d.sync += [
        #             down.eq(0),
        #             dac.o.eq(dac.o + 1)
        #         ]
        #     with m.If(dac.o == 255):
        #         m.d.sync += [
        #             down.eq(1),
        #             dac.o.eq(dac.o - 1)
        #         ]
        # with m.Else():
        #     m.d.sync += dac_cnt.eq(dac_cnt + 1)

        return m


if __name__ == "__main__":
    plat = ICEBreakerPlatform()
    prod = plat.build(Top(), debug_verilog=True)

    with prod.extract("top.bin") as bitstream_filename:
        subprocess.check_call(["openFPGALoader", "-b", "ice40_generic", bitstream_filename])


