
## ✈️ Vuelos comerciales vs privados (Jun 2026)
- `backend/flight_classifier.py`: `is_private_flight()` marks a flight private when ANY of these is true: the code looks like a registration (ECMKV, EC-NUY, D-IABC, N123AB), the aircraft is a business jet (C56X, GLEX, PC12...), or the operator is private (NetJets, VistaJet, Flexjet...). Airline codes (IB0618, I21574=Iberia Express, U2, 3O) count as commercial.
- `flight_weight()` = 0.25 for private, 1 otherwise. Applied everywhere: P/E/F/S counters, GRANDES, weighted score/winner, saturation, instant demand, street-data airport counts, daily-summary airport peaks.
- `FlightArrival.is_private` field; TerminalData count fields are now float.
- Frontend: PRIVADO badge + dimmed row (opacity 0.55, grey border), note "N vuelos privados (cuentan 0,25)", fractional counts shown with a comma.
- Tests: tests/test_flight_classifier.py (18), tests/test_flights_private_api.py (5) — iteration_25 100%.
- Known: 16 old tests in test_terminal_demand.py / test_instant_pressure.py are outdated (they expect fields that were removed earlier).
