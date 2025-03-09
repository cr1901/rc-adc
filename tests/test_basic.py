import pytest

from rc_adc.adc import AdcParams, RcAdc


@pytest.fixture
def res():
    return 8


@pytest.fixture
def mod(clks, res):
    adc_params = AdcParams(R=0.996e5, C=0.893e-9, Vdd=3.3, Vref=3.3 / 2,
                           res=res, Hz=1.0 / clks, lut_width=9)
    return RcAdc(adc_params, raw=False)


@pytest.mark.parametrize("clks", [1.0 / 12e6])
def test_overflow(sim, mod):
    async def tb(ctx):
        ctx.set(mod.ctrl.start, 1)
        await ctx.tick().until(mod.ctrl.done == 1)

        ctx.set(mod.io.sense, 1)
        await ctx.tick().repeat(140)
        ctx.set(mod.io.sense, 0)
        await ctx.tick().repeat(mod.lin.max_cnt - 140 + 1)

        dat, = await ctx.tick().sample(mod.data.val).repeat(mod.lin.discharge_cnt + 1)
        ctx.set(mod.io.sense, 1)
        assert dat == 0x3f

        dat, = await ctx.tick().sample(mod.data.val).repeat(mod.lin.max_cnt + 1)
        assert dat == 255

    sim.run(testbenches=[tb])
