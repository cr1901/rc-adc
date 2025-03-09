from dataclasses import dataclass

from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.data import StructLayout
from amaranth.lib.enum import Enum
from amaranth.lib.wiring import Signature, In, Out, Component
from amaranth import Module, Signal, unsigned
from amaranth.lib.memory import MemoryData, Memory

from . import rc


def adc_value_layout(params):
    return StructLayout({
        "val": unsigned(params.res),
        # Overflow
        "ov": unsigned(1)
    })


def adc_ctrl_signature():
    return Signature({
        # Begin charging to get ADC value.
        "start": Out(1),
        # Valid value available.
        "avail": In(1),
        # Charge/discharge cycle done.
        "done": In(1),
    })


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


class RcAdc(Component):
    """RC Circuit-Based Analog-to-Digital Converter."""

    class _State(Enum):
        # IDLE = 0b01
        CHARGE = 0b10
        DISCHARGE = 0b11

    def __init__(self, params: AdcParams, raw: bool):
        self.rc = rc.RCCircuit(params.R, params.C, params.Vdd, params.Vref)
        self.lin = rc.AdcLinearizer(self.rc, params.res, params.lut_width,
                                    params.Hz)
        self.raw = raw

        super().__init__({
            "io": Out(Signature({
                "sense": In(1),
                "charge": Out(1)
            })),
            "data": Out(adc_value_layout(params)),
            "ctrl": In(adc_ctrl_signature())
        })

    @property
    def sample_rate(self):
        """Return the sample rate of the constructed ADC."""
        return 1 / (self.rc.charge_time_max() + self.rc.drain_time_max())

    def elaborate(self, plat):  # noqa: D102
        m = Module()

        state = Signal(RcAdc._State, init=RcAdc._State.DISCHARGE)

        up_cnt = Signal(range(self.lin.max_cnt + 1))
        # In theory, we can discharge the capacitor immediately by disabling
        # the output. However, this gives the ramp waveform a sawtooth-like
        # shape and all the harmonics that come with that. My experience is
        # that this makes the comparator stop working at 75% of full range.
        # Discharging slowly gives a triangle-like wave with better harmonics
        # (at the cost of having to wait).
        down_cnt = Signal(range(self.lin.discharge_cnt + 1))
        done_stb = Signal(1)
        done_reg = Signal(1)

        zero_run = Signal(4)
        latched_cnt = Signal(1)
        raw_val = Signal(self.lin.lut_width)

        latched_adc = Signal()
        # The comparator output (from the diff input) is very sensitive. Do not
        # load it more than necessary, and also try to block metastability.
        m.submodules += FFSynchronizer(self.io.sense, latched_adc)

        m.d.comb += self.ctrl.done.eq(done_stb | done_reg)

        with m.If(state == RcAdc._State.DISCHARGE):
            m.d.comb += self.io.charge.eq(0)
            m.d.sync += down_cnt.eq(down_cnt + 1)

            with m.If(down_cnt == self.lin.discharge_cnt):
                m.d.comb += done_stb.eq(1)
                # m.d.comb += self.out[2].eq(1)
                m.d.sync += [
                    down_cnt.eq(0),
                    latched_cnt.eq(0),
                    done_reg.eq(1)
                ]

            with m.If(self.ctrl.start & self.ctrl.done):
                m.d.sync += [
                    state.eq(RcAdc._State.CHARGE),
                    self.ctrl.avail.eq(0),
                    done_reg.eq(0)
                ]

        with m.Elif(state == RcAdc._State.CHARGE):
            m.d.comb += self.io.charge.eq(1)
            m.d.sync += [
                up_cnt.eq(up_cnt + 1),
                # TODO: If using multicycle linearizer, conversion will take
                # more than one cycle. In this case, latched_cnt is a ready
                # strobe for the multiplier (and assumes multiplication takes
                # fewer cycles than the sampling period).
                self.ctrl.avail.eq(latched_cnt)
            ]

            with m.If(self.io.sense == 0):
                m.d.sync += zero_run.eq(zero_run + 1)
            with m.Else():
                m.d.sync += zero_run.eq(0)

            with m.If((zero_run == 2) & ~latched_cnt):
                m.d.sync += [
                    raw_val.eq(((up_cnt >> self.lin.clk_shift_amt) *
                                self.lin.conv_factor) >>
                               (self.lin.conv_precision)),
                    latched_cnt.eq(1)
                ]

            with m.If(up_cnt == self.lin.max_cnt):
                # m.d.comb += self.out[1].eq(1)
                m.d.sync += [
                    up_cnt.eq(0),
                    state.eq(RcAdc._State.DISCHARGE),
                    zero_run.eq(0),
                ]

        # print(self.lin.lut_entries)
        if self.raw:
            m.d.comb += self.data.val.eq(raw_val[-8:])
        else:
            mem_data = MemoryData(shape=self.lin.res,
                                  depth=2**self.lin.lut_width,
                                  init=self.lin.lut_entries)
            mem = Memory(mem_data)
            r_port = mem.read_port()

            m.d.comb += [
                r_port.en.eq(1),
                r_port.addr.eq(raw_val)
            ]

            m.d.comb += self.data.val.eq(r_port.data)
            m.submodules += mem

        # m.d.comb += [
        #     self.out[4].eq(latched_cnt),
        #     self.out[5].eq(latched_adc),
        #     self.out[6].eq(down_cnt == ice_lin.discharge_cnt)
        # ]

        return m
