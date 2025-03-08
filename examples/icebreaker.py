import subprocess

from amaranth import Module, Cat
from amaranth_boards.icebreaker import ICEBreakerPlatform
from amaranth.build import Resource, Pins, Attrs, Subsignal, DiffPairs
from amaranth_boards.resources import LEDResources

from rc_adc.adc import RcAdc, AdcParams
from rc_adc.dac import DacSweep, SweepParams

adc_ = Resource("adc", 0,
                Subsignal("ctrl", Pins("2", dir="o", conn=("pmod", 0))),
                Subsignal("sense", DiffPairs("1", "7", dir="i",
                                             conn=("pmod", 0)),
                          Attrs(IO_STANDARD="SB_LVDS_INPUT")))
dac_ = Resource("dac", 0, Pins("1 2 3 4 7 8 9 10", dir="o", conn=("pmod", 1)),
                Attrs(IO_STANDARD="SB_LVCMOS"))
leds_ = LEDResources(pins={2: "1", 3: "2", 4: "3", 5: "4",
                           6: "7", 7: "8", 8: "9", 9: "10"}, conn=("pmod", 2),
                     attrs=Attrs(IO_STANDARD="SB_LVCMOS"))
debug_ = Resource("debug", 0,
                  Subsignal("latched", Pins("10", dir="o", conn=("pmod", 0))),
                  Subsignal("sense", Pins("4", dir="o", conn=("pmod", 0))),
                  Subsignal("start", Pins("9", dir="o", conn=("pmod", 0))))


if __name__ == "__main__":
    plat = ICEBreakerPlatform()
    plat.add_resources([adc_, dac_, *leds_, debug_])

    # Make sure to measure R and C_... The ADC is sensitive to its values!
    # R = 1e5
    # C_ = 1e-9
    adc_params = AdcParams(R=0.996e5, C=0.893e-9, Vdd=3.3, Vref=3.3 / 2, res=8,
                           Hz=12e6, lut_width=9)
    adc = RcAdc(adc_params, raw=False)

    sweep_params = SweepParams(Vdd=3.3, Vref=3.3 / 2, clk_Hz=12e6,
                               sweep_Hz=1)
    sweep = DacSweep(sweep_params)

    top = Module()
    top.submodules += adc, sweep

    leds = Cat(plat.request("led", i).o for i in range(2, 10))
    adc_pins = plat.request("adc")
    dac = plat.request("dac")
    # debug = plat.request("debug")

    top.d.comb += [
        dac.o.eq(sweep.dac),
        adc.sense.eq(adc_pins.sense.i),
        adc_pins.ctrl.o.eq(adc.ctrl),
        leds.eq(adc.out)
    ]

    print(adc.sample_rate)
    prod = plat.build(top, debug_verilog=True)

    with prod.extract("top.bin") as bitstream_filename:
        subprocess.check_call(["openFPGALoader", "-b", "ice40_generic",
                               bitstream_filename])
