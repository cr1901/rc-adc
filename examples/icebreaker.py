import math
import subprocess

from amaranth import Elaboratable, Module, Cat, Signal, C
from amaranth_boards.icebreaker import ICEBreakerPlatform
from amaranth.build import Resource, Pins, Attrs, Subsignal, DiffPairs
from amaranth_boards.resources import LEDResources
from amaranth_stdio.serial import AsyncSerial

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


# Taken from: https://github.com/amaranth-lang/amaranth/blob/f9da3c0d166dd2be189945dca5a94e781e74afeb/examples/basic/uart.py  # noqa: E501
class UART(Elaboratable):
    """Basic hardcoded UART.

    Parameters
    ----------
    divisor : int
        Set to ``round(clk-rate / baud-rate)``.
        E.g. ``12e6 / 115200`` = ``104``.

    data_bits : int
        Number of data bits in character.
    """

    def __init__(self, divisor, data_bits=8):
        assert divisor >= 4

        self.data_bits = data_bits
        self.divisor = divisor

        self.tx_o = Signal()
        self.rx_i = Signal()

        self.tx_data = Signal(data_bits)
        self.tx_rdy = Signal()
        self.tx_ack = Signal()

        self.rx_data = Signal(data_bits)
        self.rx_err = Signal()
        self.rx_ovf = Signal()
        self.rx_rdy = Signal()
        self.rx_ack = Signal()

    def elaborate(self, platform):  # noqa: D102
        m = Module()

        tx_phase = Signal(range(self.divisor))
        tx_shreg = Signal(1 + self.data_bits + 1, reset=-1)
        tx_count = Signal(range(len(tx_shreg) + 1))

        m.d.comb += self.tx_o.eq(tx_shreg[0])
        with m.If(tx_count == 0):
            m.d.comb += self.tx_ack.eq(1)
            with m.If(self.tx_rdy):
                m.d.sync += [
                    tx_shreg.eq(Cat(C(0, 1), self.tx_data, C(1, 1))),
                    tx_count.eq(len(tx_shreg)),
                    tx_phase.eq(self.divisor - 1),
                ]
        with m.Else():
            with m.If(tx_phase != 0):
                m.d.sync += tx_phase.eq(tx_phase - 1)
            with m.Else():
                m.d.sync += [
                    tx_shreg.eq(Cat(tx_shreg[1:], C(1, 1))),
                    tx_count.eq(tx_count - 1),
                    tx_phase.eq(self.divisor - 1),
                ]

        rx_phase = Signal(range(self.divisor))
        rx_shreg = Signal(1 + self.data_bits + 1, reset=-1)
        rx_count = Signal(range(len(rx_shreg) + 1))

        m.d.comb += self.rx_data.eq(rx_shreg[1:-1])
        with m.If(rx_count == 0):
            m.d.comb += self.rx_err.eq(~(~rx_shreg[0] & rx_shreg[-1]))
            with m.If(~self.rx_i):
                with m.If(self.rx_ack | ~self.rx_rdy):
                    m.d.sync += [
                        self.rx_rdy.eq(0),
                        self.rx_ovf.eq(0),
                        rx_count.eq(len(rx_shreg)),
                        rx_phase.eq(self.divisor // 2),
                    ]
                with m.Else():
                    m.d.sync += self.rx_ovf.eq(1)
            with m.If(self.rx_ack):
                m.d.sync += self.rx_rdy.eq(0)
        with m.Else():
            with m.If(rx_phase != 0):
                m.d.sync += rx_phase.eq(rx_phase - 1)
            with m.Else():
                m.d.sync += [
                    rx_shreg.eq(Cat(rx_shreg[1:], self.rx_i)),
                    rx_count.eq(rx_count - 1),
                    rx_phase.eq(self.divisor - 1),
                ]
                with m.If(rx_count == 1):
                    m.d.sync += self.rx_rdy.eq(1)

        return m


if __name__ == "__main__":
    plat = ICEBreakerPlatform()
    plat.add_resources([adc_, dac_, *leds_, debug_])

    # Make sure to measure R and C_... The ADC is sensitive to its values!
    # R = 1e5
    # C_ = 1e-9
    adc_params = AdcParams(R=0.996e5, C=0.893e-9, Vdd=3.3, Vref=(3.3 / 2),
                           res=8, Hz=12e6, lut_width=10, thresh=0.120)
    adc = RcAdc(adc_params, raw=False)

    sweep_params = SweepParams(Vdd=3.3, Vref=3.3 / 2, clk_Hz=12e6,
                               sweep_Hz=1)
    sweep = DacSweep(sweep_params)

    uart = UART(divisor=int(12e6 // 115200))
    uart_pins = plat.request("uart")

    top = Module()
    top.submodules += adc, sweep, uart

    leds = Cat(plat.request("led", i).o for i in range(2, 10))
    adc_pins = plat.request("adc")
    dac = plat.request("dac")

    # debug = plat.request("debug")

    top.d.comb += [
        adc.ctrl.start.eq(1),
        dac.o.eq(sweep.dac),
        adc.io.sense.eq(adc_pins.sense.i),
        adc_pins.ctrl.o.eq(adc.io.charge),
        leds.eq(adc.data.val),
        uart_pins.tx.o.eq(uart.tx_o),
        uart.rx_i.eq(uart_pins.rx.i)
    ]

    stage = Signal(3)
    adc_val = Signal(8)
    dac_val = Signal(8)
    sample_count = Signal(range(math.ceil(adc.sample_rate)))
    sample_en = Signal(1)

    with top.If(sample_en):
        top.d.sync += sample_count.eq(sample_count + 1)

    with top.If(uart.rx_rdy & adc.ctrl.done & (stage == 0)):
        top.d.comb += [
            sample_en.eq(1),
            uart.rx_ack.eq(1)
        ]
        top.d.sync += [
            dac_val.eq(sweep.dac),
            adc_val.eq(adc.data.val),
            stage.eq(1)
        ]

    with top.Elif(stage == 1):
        top.d.comb += [
            uart.tx_data.eq(dac_val),
            uart.tx_rdy.eq(1)
        ]
        top.d.sync += stage.eq(2)

    with top.Elif(uart.tx_ack & (stage == 2)):
        top.d.comb += [
            uart.tx_data.eq(adc_val),
            uart.tx_rdy.eq(1)
        ]
        top.d.sync += stage.eq(3)

    with top.Elif(adc.ctrl.done & (stage == 3)):
        with top.If(sample_count == (math.ceil(adc.sample_rate) - 1)):
            top.d.sync += [
                stage.eq(0),
                sample_count.eq(0)
            ]
        with top.Else():
            top.d.comb += sample_en.eq(1)
            top.d.sync += [
                dac_val.eq(sweep.dac),
                adc_val.eq(adc.data.val),
                stage.eq(1)
            ]

    print(adc.sample_rate)
    print(adc.sample_rate_theoretical)
    prod = plat.build(top, debug_verilog=True)

    with prod.extract("top.bin") as bitstream_filename:
        subprocess.check_call(["openFPGALoader", "-b", "ice40_generic",
                               bitstream_filename])
