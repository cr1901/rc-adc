# ruff: noqa: F405

import math
import subprocess

from amaranth import Elaboratable, Memory, Module, Cat, Signal, C
from amaranth.lib.memory import Memory, MemoryData
from amaranth_boards.icebreaker import ICEBreakerPlatform
from amaranth.build import Resource, Pins, Attrs, Subsignal, DiffPairs
from amaranth_boards.resources import LEDResources
from amaranth_stdio.serial import AsyncSerial

from boneless.gateware import CoreFSM
from boneless.arch.opcode import Instr
from boneless.arch.opcode import *

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


UART_RX_RDY = 0
UART_RX_DATA = 1
UART_TX_ACK = 2
UART_TX_DATA = 3
SAMPLE_RDY = 4
DAC_VAL_COPY = 5
ADC_VAL_COPY = 6
ADC_IDX_COPY = 7
ADC_CNT_COPY = 8


def firmware(sample_rate):
    """Driver program to synchronize and load DAC/ADC samples over UART."""
    STAGES = ["idle",
              "load_dac",
              "load_adc",
              "wait_or_finish"
    ]
    ADC_TYPE = ["val", "idx_or_cmp", "idx_or_cmp", "none"]

    def jump_table(*args):
        def relocate(resolver):
            return [resolver(arg) for arg in args]
        return relocate

    RET_PTR = R0
    STAGE = R1
    DAC_VAL = R4
    ADC_VAL = R5
    XFER_TYPE = R6
    # JMPTAB = R2
    CNT = R7

    return [  # noqa: DOC201
        MOVI(STAGE, 0),
        MOVI(CNT, 0),
    L("loop"),
        JST(STAGE, "jmptab"),

    L("jmptab"),
    jump_table(*STAGES),

    L("idle"),
        JAL(RET_PTR, "sync_rx"),
        MOV(XFER_TYPE, R3),
    L("no_match"),
        JAL(RET_PTR, "sync_sample"),
        LDXA(DAC_VAL, DAC_VAL_COPY),
        ANDI(R2, XFER_TYPE, 0b00011100),
        BZ0("wait_match"),
        J("save_adc"),
    L("wait_match"),
        SRLI(R2, R2, 2),
        LDR(R3, R2, "sync_vals"),
        CMP(R3, DAC_VAL),
        BNE("no_match"),
        J("save_adc"),

    L("load_dac"),
        MOV(R3, DAC_VAL),
        JAL(RET_PTR, "wait_then_tx"),
        MOVI(STAGE, STAGES.index("load_adc")),
        J("loop"),

    L("load_adc"),
        ANDI(R2, XFER_TYPE, 0b00000011),
        JST(R2, "adc_jmptab"),

    L("adc_jmptab"),
        jump_table(*ADC_TYPE),

    L("val"),
        MOV(R3, ADC_VAL),
        JAL(RET_PTR, "wait_then_tx"),
        J("adc_epilog"),

    L("idx_or_cmp"),
        MOV(R3, ADC_VAL),
        JAL(RET_PTR, "wait_then_tx"),
        SRLI(R3, R3, 8),
        JAL(RET_PTR, "wait_then_tx"),
        J("adc_epilog"),

    L("none"),
    L("adc_epilog"),
        MOVI(STAGE, STAGES.index("wait_or_finish")),
        J("loop"),

    L("wait_or_finish"),
        ADDI(CNT, CNT, 1),
        CMPI(CNT, sample_rate),
        BZ1("finish"),

    L("wait"),
        JAL(RET_PTR, "sync_sample"),
        LDXA(DAC_VAL, DAC_VAL_COPY),
        J("save_adc"),

    L("finish"),
        MOVI(CNT, 0),
        MOVI(STAGE, STAGES.index("idle")),
        J("loop"),

    # Subroutines
    # R0- Return, R3- Val to send, R2- Temp
    L("wait_then_tx"),
        LDXA(R2, UART_TX_ACK),
        ANDI(R2, R2, 1),
        BZ1("wait_then_tx"),
        STXA(R3, UART_TX_DATA),
        JR(R0, 0),

    # R0- Return, R2- Temp
    L("sync_sample"),
        LDXA(R2, SAMPLE_RDY),
        ANDI(R2, R2, 1),
        BZ1("sync_sample"),
        JR(R0, 0),

    # R0- Return, R3- Received val, R2- Temp
    L("sync_rx"),
        LDXA(R2, UART_RX_RDY),
        ANDI(R2, R2, 1),
        BZ1("sync_rx"),
        LDXA(R3, UART_RX_DATA),
        JR(R0, 0),

    # Tail call
    L("save_adc"),
        # Keep xfer type around so we know whether to send one byte or two
        # for each xfer.
        ANDI(R2, XFER_TYPE, 0b00000011),
        LDX(ADC_VAL, R2, ADC_VAL_COPY),
        MOVI(STAGE, STAGES.index("load_dac")),
        J("loop"),

    # Constant Data
    L("sync_vals"),
        0,  # None Val
        0,
        64,
        127,
        255
    ]


if __name__ == "__main__":
    plat = ICEBreakerPlatform()
    plat.add_resources([adc_, dac_, *leds_, debug_])

    # Make sure to measure R and C_... The ADC is sensitive to its values!
    # R = 1e5
    # C_ = 1e-9
    adc_params = AdcParams(R=0.996e5, C=0.893e-9, Vdd=3.3, Vref=(3.3 / 2),
                           res=8, Hz=12e6, lut_width=9, thresh=0.120)
    adc = RcAdc(adc_params, debug=True)

    sweep_params = SweepParams(Vdd=3.3, Vref=3.3 / 2, clk_Hz=12e6,
                               sweep_Hz=1)
    sweep = DacSweep(sweep_params)

    uart = UART(divisor=int(12e6 // 115200))
    uart_pins = plat.request("uart")

    firm_bytes = Instr.assemble(firmware(
        sample_rate=math.ceil(adc.sample_rate)))
    print(Instr.disassemble(firm_bytes))
    firm_data = MemoryData(shape=16, depth=256, init=firm_bytes)
    cpu = CoreFSM(mem_data=firm_data)

    top = Module()
    top.submodules += adc, sweep, uart, cpu

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

    sample_rdy = Signal(1)
    adc_val = Signal(8)
    adc_idx = Signal(adc_params.lut_width)
    adc_cnt = Signal(range(adc.lin.max_cnt + 1))
    dac_val = Signal(8)

    with top.If(cpu.o_ext_we):
        with top.Switch(cpu.o_bus_addr):
            with top.Case(UART_TX_DATA):
                top.d.comb += [
                    uart.tx_data.eq(cpu.o_ext_data),
                    uart.tx_rdy.eq(1)
                ]

    with top.If(cpu.o_ext_re):
        with top.Switch(cpu.o_bus_addr):
            with top.Case(UART_RX_RDY):
                top.d.sync += cpu.i_ext_data.eq(uart.rx_rdy)
            with top.Case(UART_RX_DATA):
                top.d.sync += cpu.i_ext_data.eq(uart.rx_data)
                top.d.comb += uart.rx_ack.eq(1)
            with top.Case(UART_TX_ACK):
                top.d.sync += cpu.i_ext_data.eq(uart.tx_ack)
            with top.Case(SAMPLE_RDY):
                top.d.sync += [
                    cpu.i_ext_data.eq(sample_rdy),
                    sample_rdy.eq(0)
                ]
            with top.Case(DAC_VAL_COPY):
                top.d.sync += cpu.i_ext_data.eq(dac_val)
            with top.Case(ADC_VAL_COPY):
                top.d.sync += cpu.i_ext_data.eq(adc_val)
            with top.Case(ADC_IDX_COPY):
                top.d.sync += cpu.i_ext_data.eq(adc_idx)
            with top.Case(ADC_CNT_COPY):
                top.d.sync += cpu.i_ext_data.eq(adc_cnt)

    # ADC done is a strobe, so latch all the data we need in copies.
    with top.If(adc.ctrl.done):
        top.d.sync += [
            dac_val.eq(sweep.dac),
            adc_val.eq(adc.data.val),
            adc_idx.eq(adc.debug.idx),
            adc_cnt.eq(adc.debug.cnt),
            sample_rdy.eq(1)
        ]

    print(adc.sample_rate)
    print(adc.sample_rate_theoretical)
    prod = plat.build(top, debug_verilog=True)

    with prod.extract("top.bin") as bitstream_filename:
        subprocess.check_call(["openFPGALoader", "-b", "ice40_generic",
                               bitstream_filename])
