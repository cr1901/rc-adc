import math


# TODO: Check max current draw. For a given C, max current across R needs to
# be less than the I/O's drive.

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
    def __init__(self, rc, res, lut_width, Hz, thresh=0.0):
        self.rc = rc
        self.res = res
        self.lut_width = lut_width
        self.Hz = Hz
        self.thresh = thresh  # Negation of the Offset Error- i.e. thresh
        # of 0.060 mV means Offset Error of -0.060 mV.

        self.clk_shift_amt = self.max_cnt.bit_length() - self.lut_width
        self.conv_precision = 16 - lut_width

        # 0..max_clocks => 0..2**lut_width - 1
        self.conv_factor = int(2**lut_width * 2**self.conv_precision) // \
            (self.max_cnt >> self.clk_shift_amt)  # Qlut_width.conv_precision // Qlut_width.0  # noqa: E501

        self.lut_entries = []
        self.raw_entries = []

        thresh_digital = self.V_to_digital_theoretical(self.thresh)
        thresh_start_idx = self.digital_to_idx(thresh_digital)

        for i in range(2**lut_width):
            # Account for the time saved from the (charging) negative side
            # of the comparator to go within "thresh" volts below the
            # (measured) positive side. Generally, the time it takes for sense
            # to go low will be shorter than theoretical. Without a correction,
            # the ADC will undershoot the actual voltage that's on the positive
            # terminal. We shift the sample time so that 0 sample time
            # corresponds to "thresh" volt difference.
            sample_time = (self.rc.charge_time_max() * (i + thresh_start_idx)) / 2**lut_width
            raw_entry = (self.rc.Vout(sample_time, Vc_begin=0) *
                         (1 / self.rc.Vref) *
                         (2**res))

            # Assuming sense doesn't go low before taking a measurement even
            # begins, the actual voltages differences detected on the
            # comparator will naturally bottom out at around "thresh volts".
            # There will probably be a LSB or 2 of LUT entries left over to
            # represent noise resulting in counts ("number of clock cycles for
            # sense to go low") that corresponds the range 0V to
            # "thresh volts". Attempt to stretch this region down to 0 volts.
            #
            # Using the first 8 LUT entries to represent 0 to "thresh"
            # is somewhat arbitrary; feel free to experiment with different
            # values. LUT indices "2" or "4", or even "0" for an 8-bit ADC are
            # also reasonable candidates (at the cost of more lower-end range).
            if i >= 8:
                entry = int(raw_entry)
            else:
                entry = int(raw_entry * i / 8)

            self.raw_entries.append(raw_entry)
            self.lut_entries.append(entry if entry < 2**res else 2**res - 1)

    @property
    def max_time(self):
        return self.rc.charge_time_max()

    @property
    def discharge_time(self):
        return self.rc.drain_time_max()

    @property
    def max_cnt(self):
        """Return number of clocks to charge, rounded up.

        Pass this count as a :class:`range` to the
        :ref:`Signal <amaranth:lang-signals>` constructor.
        """
        return int(math.ceil(self.Hz * self.max_time))

    @property
    def discharge_cnt(self):
        """Return number of clocks to discharge, rounded up.

        Pass this count as a :class:`range` to the
        :ref:`Signal <amaranth:lang-signals>` constructor.
        """
        return int(math.ceil(self.Hz * self.discharge_time))

    def cnt_to_idx(self, c):
        return math.floor((c >> self.clk_shift_amt) * self.conv_factor) >> \
                          self.conv_precision

    def cnt_to_digital(self, c):
        return self.lut_entries[self.cnt_to_idx(c)]

    def cnt_to_V(self, c):
        return self.cnt_to_digital(c) * (self.rc.Vref / (2**self.res))

    def V_to_digital(self, v):
        return self.cnt_to_digital(self.V_to_cnt(v))

    def V_to_digital_theoretical(self, v):
        return round((2**self.res * v) / self.rc.Vref)

    def V_to_idx(self, v):
        return self.cnt_to_idx(self.V_to_cnt(v))

    def V_to_cnt(self, v):
        return math.ceil(int(self.Hz * self.rc.charge_time(0, v)))

    def digital_to_cnt(self, d):
        return self.V_to_cnt(self.digital_to_V(d))

    def digital_to_idx(self, d):
        return self.V_to_idx(self.digital_to_V(d))

    def digital_to_V(self, d):
        return (self.rc.Vref * d) / (2**self.res)
