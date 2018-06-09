import pytest
import functools
import numpy as np

from scipy.integrate import solve_ivp
from poliastro.integrators import DOP835

from astropy.time import Time
from poliastro.twobody.propagation import cowell, func_twobody
from poliastro.twobody.rv import rv2coe
from poliastro.ephem import build_ephem_interpolant
from astropy import units as u
from poliastro.util import norm
from poliastro.twobody.perturbations import J2_perturbation, atmospheric_drag, third_body
from poliastro.bodies import Earth, Moon, Sun
from astropy.tests.helper import assert_quantity_allclose
from poliastro.twobody import Orbit
# from poliastro.coordinates import transform
from astropy.coordinates import ICRS, GCRS


def test_J2_propagation_Earth():
    # from Curtis example 12.2:
    r0 = np.array([-2384.46, 5729.01, 3050.46])  # km
    v0 = np.array([-7.36138, -2.98997, 1.64354])  # km/s
    k = Earth.k.to(u.km**3 / u.s**2).value

    orbit = Orbit.from_vectors(Earth, r0 * u.km, v0 * u.km / u.s)

    tof = (48.0 * u.h).to(u.s).value
    r, v = cowell(orbit, tof, ad=J2_perturbation, J2=Earth.J2.value, R=Earth.R.to(u.km).value)

    _, _, _, raan0, argp0, _ = rv2coe(k, r0, v0)
    _, _, _, raan, argp, _ = rv2coe(k, r, v)

    raan_variation_rate = (raan - raan0) / tof
    argp_variation_rate = (argp - argp0) / tof

    raan_variation_rate = (raan_variation_rate * u.rad / u.s).to(u.deg / u.h)
    argp_variation_rate = (argp_variation_rate * u.rad / u.s).to(u.deg / u.h)

    assert_quantity_allclose(raan_variation_rate, -0.172 * u.deg / u.h, rtol=1e-2)
    assert_quantity_allclose(argp_variation_rate, 0.282 * u.deg / u.h, rtol=1e-2)


def test_atmospheric_drag():
    # http://farside.ph.utexas.edu/teaching/celestial/Celestialhtml/node94.html#sair (10.148)
    # given the expression for \dot{r} / r, aproximate \Delta r \approx F_r * \Delta t

    R = Earth.R.to(u.km).value
    k = Earth.k.to(u.km**3 / u.s**2).value

    # parameters of a circular orbit with h = 250 km (any value would do, but not too small)
    orbit = Orbit.circular(Earth, 250 * u.km)
    r0, _ = orbit.rv()
    r0 = r0.to(u.km).value

    # parameters of a body
    C_D = 2.2  # dimentionless (any value would do)
    A = ((np.pi / 4.0) * (u.m**2)).to(u.km**2).value  # km^2
    m = 100  # kg
    B = C_D * A / m

    # parameters of the atmosphere
    rho0 = Earth.rho0.to(u.kg / u.km**3).value  # kg/km^3
    H0 = Earth.H0.to(u.km).value
    tof = 100000  # s

    dr_expected = -B * rho0 * np.exp(-(norm(r0) - R) / H0) * np.sqrt(k * norm(r0)) * tof
    # assuming the atmospheric decay during tof is small,
    # dr_expected = F_r * tof (Newton's integration formula), where
    # F_r = -B rho(r) |r|^2 sqrt(k / |r|^3) = -B rho(r) sqrt(k |r|)

    r, v = cowell(orbit, tof, ad=atmospheric_drag, R=R, C_D=C_D, A=A, m=m, H0=H0, rho0=rho0)

    assert_quantity_allclose(norm(r) - norm(r0), dr_expected, rtol=1e-2)


def test_cowell_works_with_small_perturbations():
    r0 = [-2384.46, 5729.01, 3050.46] * u.km
    v0 = [-7.36138, -2.98997, 1.64354] * u.km / u.s

    r_expected = [13179.39566663877121754922, -13026.25123408228319021873, -9852.66213692844394245185] * u.km
    v_expected = [2.78170542314378943516, 3.21596786944631274352, 0.16327165546278937791] * u.km / u.s

    initial = Orbit.from_vectors(Earth, r0, v0)

    def accel(t0, state, k):
        v_vec = state[3:]
        norm_v = (v_vec * v_vec).sum() ** .5
        return 1e-5 * v_vec / norm_v

    final = initial.propagate(3 * u.day, method=cowell, ad=accel)

    assert_quantity_allclose(final.r, r_expected)
    assert_quantity_allclose(final.v, v_expected)


def test_cowell_converges_with_small_perturbations():
    r0 = [-2384.46, 5729.01, 3050.46] * u.km
    v0 = [-7.36138, -2.98997, 1.64354] * u.km / u.s

    initial = Orbit.from_vectors(Earth, r0, v0)

    def accel(t0, state, k):
        v_vec = state[3:]
        norm_v = (v_vec * v_vec).sum() ** .5
        return 0.0 * v_vec / norm_v

    final = initial.propagate(initial.period, method=cowell, ad=accel)
    assert_quantity_allclose(final.r, initial.r)
    assert_quantity_allclose(final.v, initial.v)


moon_heo = {'body': Moon, 'tof': 60, 'raan': -0.06 * u.deg, 'argp': 0.15 * u.deg, 'inc': 0.08 * u.deg,
            'orbit': [26553.4 * u.km, 0.741 * u.one, 63.4 * u.deg, 0.0 * u.deg, 270 * u.deg, 0.0 * u.rad]}

moon_leo = {'body': Moon, 'tof': 60, 'raan': -2.18 * 1e-4 * u.deg,
            'argp': 1.5 * 1e-2 * u.deg, 'inc': 6.0 * 1e-4 * u.deg,
            'orbit': [6678.126 * u.km, 0.01 * u.one, 28.5 * u.deg, 0.0 * u.deg, 0.0 * u.deg, 0.0 * u.rad]}

moon_geo = {'body': Moon, 'tof': 60, 'raan': 6.0 * u.deg, 'argp': -11.0 * u.deg, 'inc': 6.0 * 1e-3 * u.deg,
            'orbit': [42164.0 * u.km, 0.0001 * u.one, 1 * u.deg, 0.0 * u.deg, 0.0 * u.deg, 0.0 * u.rad]}

sun_heo = {'body': Sun, 'tof': 200, 'raan': -5.0 * 1e-3 * u.deg, 'argp': 0.12 * u.deg, 'inc': 1.0 * 1e-4 * u.deg,
           'orbit': [26553.4 * u.km, 0.741 * u.one, 63.4 * u.deg, 0.0 * u.deg, 270 * u.deg, 0.0 * u.rad]}

sun_leo = {'body': Sun, 'tof': 200, 'raan': -5.0 * 1e-3 * u.deg, 'argp': 0.12 * u.deg, 'inc': 1.0 * 1e-4 * u.deg,
           'orbit': [6678.126 * u.km, 0.01 * u.one, 28.5 * u.deg, 0.0 * u.deg, 0.0 * u.deg, 0.0 * u.rad]}

sun_geo = {'body': Sun, 'tof': 200, 'raan': -5.0 * 1e-3 * u.deg, 'argp': 0.12 * u.deg, 'inc': 1.0 * 1e-4 * u.deg,
           'orbit': [42164.0 * u.km, 0.0001 * u.one, 1 * u.deg, 0.0 * u.deg, 0.0 * u.deg, 0.0 * u.rad]}


@pytest.mark.xfail
@pytest.mark.parametrize('test_params', [
    moon_heo, moon_geo, moon_leo,
    sun_heo, sun_geo, sun_leo
])
def test_3rd_body_Curtis(test_params):
    # based on example 12.11 from Howard Curtis
    body = test_params['body']
    tof_days = test_params['tof']

    j_date = 2454283.0
    tof = (tof_days * u.day).to(u.s).value
    body_r = build_ephem_interpolant(body, (j_date, j_date + tof_days), rtol=1e-2)

    epoch = Time(j_date, format='jd', scale='tdb')
    initial = Orbit.from_classical(Earth, *test_params['orbit'], epoch=epoch)

    r, v = cowell(initial, tof, rtol=1e-8, ad=third_body,
                  k_third=body.k.to(u.km**3 / u.s**2).value, third_body=body_r)
    _, _, inc_f, raan_f, argp_f, _ = rv2coe(Earth.k.to(u.km**3 / u.s**2).value, r, v)

    assert_quantity_allclose([(raan_f * u.rad).to(u.deg) - test_params['raan'],
                              (argp_f * u.rad).to(u.deg) - test_params['argp'],
                              (inc_f * u.rad).to(u.deg) - test_params['inc']],
                             answer, rtol=1e-1)


@pytest.mark.xfail
@pytest.mark.parametrize('test_params', [
    [Moon, 0.00169, -0.00338],
    [Sun, 0.00077, -0.00154]
])
def test_variation_rates(test_params):
    # based on Cowell, example 12.10
    body = test_params[0]
    argp_change = test_params[1]
    raan_change = test_params[2]

    j_date = 2454283.0
    tof_days = 10
    tof = (tof_days * u.day).to(u.s).value
    body_r = build_ephem_interpolant(body, (j_date, j_date + tof_days), rtol=1e-2)

    epoch = Time(j_date, format='jd', scale='tdb')
    initial = Orbit.from_classical(Earth, *moon_geo['orbit'], epoch=epoch)

    r, v = cowell(initial, tof, rtol=1e-12, ad=third_body,
                  k_third=body.k.to(u.km**3 / u.s**2).value, third_body=body_r)
    a_f, ecc_f, inc_f, raan_f, argp_f, _ = rv2coe(Earth.k.to(u.km**3 / u.s**2).value, r, v)

    period = (2 * np.pi * np.sqrt(a ** 3 / Earth.k)).to(u.s)
    revolutions_per_day = ((1.0 * u.day).to(u.s) / period).value

    expected_argp_change_rate = argp_change * (4.0 - 5 * np.sin(inc) ** 2) / revolutions_per_day
    result_argp_change_rate = ((argp_f - argp_i) * u.rad / tof / u.s).to(u.deg / u.day).value

    expected_raan_change_rate = raan_change * np.cos(inc) / revolutions_per_day
    result_raan_change_rate = ((raan_f - raan_i) * u.rad / tof / u.s).to(u.deg / u.day).value

    assert_quantity_allclose([expected_argp_change_rate, expected_raan_change_rate],
                             [result_argp_change_rate, result_raan_change_rate])
