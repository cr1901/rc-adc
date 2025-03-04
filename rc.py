import math


class RCCircuit:
    def __init__(self, R, C, Vdd, Vref):
        self.RC = R * C
        self.Vdd = Vdd
        self.Vref = Vref

    def charge_time_max(self):
        return self.charge_time(0, self.Vref)

    def drain_time_max(self):
        return self.RC * 6

    def charge_time(self, Vc_begin, Vc_end):
        return -self.RC*math.log(1 - ((Vc_end - Vc_begin) /
                                      (self.Vdd - Vc_begin)))

    def Vout(self, t, Vc_begin):
        return (self.Vdd - Vc_begin)*(1 - math.exp(-t/self.RC)) + Vc_begin

    def sample_rate(self):
        return 1 / (self.charge_time_max() + self.drain_time_max())


class AdcLinearizer:
    def __init__(self, rc, res, lut_width, Hz):
        self.rc = rc
        self.res = res
        self.lut_width = lut_width
        self.Hz = Hz

        self.clk_shift_amt = self.max_cnt.bit_length() - self.lut_width
        self.conv_precision = 16 - lut_width

        # 0..max_clocks => 0..2**lut_width - 1
        self.conv_factor = int(2**lut_width * 2**self.conv_precision) // \
            (self.max_cnt >> self.clk_shift_amt)  # Qlut_width.conv_precision // Qlut_width.0  # noqa: E501

        self.lut_entries = []
        self.raw_entries = []
        for i in range(2**lut_width):
            sample_time = (self.rc.charge_time_max() * i) / 2**lut_width
            raw_entry = (self.rc.Vout(sample_time, Vc_begin=0) *
                         (1 / self.rc.Vref) *
                         (2**res))
            entry = int(raw_entry)

            self.raw_entries.append(raw_entry)
            self.lut_entries.append(entry)

    @property
    def max_time(self):
        return self.rc.charge_time_max()

    @property
    def discharge_time(self):
        return self.rc.drain_time_max()

    @property
    def max_cnt(self):
        return int(math.ceil(self.Hz*self.max_time))

    @property
    def discharge_cnt(self):
        return int(math.ceil(self.Hz*self.discharge_time))

    def cnt_to_digital(self, t):
        idx = math.floor((t >> self.clk_shift_amt) * self.conv_factor) >> \
              self.conv_precision
        return self.lut_entries[idx]

    def cnt_to_V(self, t):
        return self.cnt_to_digital(t) * (self.rc.Vref / (2**self.res))

    def V_to_digital(self, v):
        return self.cnt_to_digital(int(self.Hz*self.rc.charge_time(0, v)))
