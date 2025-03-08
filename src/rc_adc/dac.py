from dataclasses import dataclass

from amaranth import Module, Elaboratable, Signal


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


class DacSweep(Elaboratable):
    """Triangle-wave signal sweep for PMOD R2R."""

    def __init__(self, params: SweepParams):
        self.peak_val = int(255 * (params.Vref / params.Vdd))
        self.clk_Hz = params.clk_Hz
        self.sweep_Hz = params.sweep_Hz
        self.dac = Signal(8)

    def elaborate(self, plat):  # noqa: D102
        m = Module()

        # A sweep takes twices as many transitions as a ramp from 0 to max
        sweep_max = int((self.clk_Hz // (self.peak_val * self.sweep_Hz))) // 2

        dac_cnt = Signal(range(sweep_max + 1))
        down = Signal(1)

        # DAC sweep code.
        with m.If(dac_cnt == sweep_max):
            m.d.sync += [
                dac_cnt.eq(0)
            ]
            with m.If(down):
                m.d.sync += self.dac.eq(self.dac - 1)
            with m.Else():
                m.d.sync += self.dac.eq(self.dac + 1)

            with m.If(self.dac == 0):
                m.d.sync += [
                    down.eq(0),
                    self.dac.eq(self.dac + 1)
                ]
            # with m.If(self.dac == 255):
            with m.If(self.dac == self.peak_val):
                m.d.sync += [
                    down.eq(1),
                    self.dac.eq(self.dac - 1)
                ]
        with m.Else():
            m.d.sync += dac_cnt.eq(dac_cnt + 1)

        return m
