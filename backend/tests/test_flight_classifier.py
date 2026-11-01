import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from flight_classifier import flight_weight, is_private_flight, looks_like_registration  # noqa: E402


@pytest.mark.parametrize("fn", ["IB0618", "I21574", "IB0422S", "FR2016", "3O123", "U21234", "UX1234", "RYR123", "7736"])
def test_commercial_flight_numbers(fn):
    assert not looks_like_registration(fn)
    assert not is_private_flight(fn, "Some Airline")


@pytest.mark.parametrize("fn", ["ECMKV", "EC-NUY", "D-IABC", "N123AB", "GLXJT", "9H-VJA"])
def test_registration_flight_numbers(fn):
    assert looks_like_registration(fn)
    assert is_private_flight(fn, "")


def test_business_aircraft_and_operator():
    assert is_private_flight("UX1234", "Air Europa", "C56X")
    assert is_private_flight("VJT123", "", None, "VJT")
    assert is_private_flight("XX123", "NetJets Europe")
    assert not is_private_flight("FR2016", "Ryanair", "738W", "RYR")


def test_weight():
    assert flight_weight({"is_private": True}) == 0.25
    assert flight_weight({"is_private": False}) == 1
    assert flight_weight({}) == 1


def test_instant_demand_weighting():
    from server import calculate_instant_demand
    commercial = [{"status": "En tierra", "time": "", "aircraft": "A320"}] * 4
    private = [{"status": "En tierra", "time": "", "aircraft": "C56X", "is_private": True}] * 4
    assert calculate_instant_demand(commercial)["points"] == 0.8
    assert calculate_instant_demand(private)["points"] == 0.2
