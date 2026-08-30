"""The hygiene checks must REFUSE. A check that has never failed is not in force."""
import signal
import sys

import pytest

import carla_determinism as cd


class _Actor:
    def __init__(self, id_, type_id):
        self.id, self.type_id = id_, type_id


class _World:
    def __init__(self, actors):
        self._a = actors

    def get_actors(self):
        return self._a


def test_clean_world_accepts_empty():
    assert cd.require_clean_world(_World([]))


def test_clean_world_accepts_non_actor_props():
    # Spectators and traffic lights are part of the map, not a previous run's leftovers.
    assert cd.require_clean_world(_World([_Actor(1, "spectator"),
                                          _Actor(2, "traffic.traffic_light")]))


def test_clean_world_refuses_leftover_vehicle():
    with pytest.raises(RuntimeError, match="REFUSING"):
        cd.require_clean_world(_World([_Actor(318, "vehicle.tesla.model3")]))


def test_clean_world_refuses_leftover_sensor():
    with pytest.raises(RuntimeError, match="REFUSING"):
        cd.require_clean_world(_World([_Actor(319, "sensor.camera.rgb")]))


def test_fresh_server_refuses_a_stale_one(monkeypatch):
    monkeypatch.setattr(cd, "server_age_s", lambda port: 7200.0)
    monkeypatch.setattr(cd.hygiene, "server_age_s", lambda port: 7200.0)
    with pytest.raises(RuntimeError, match="REFUSING"):
        cd.require_fresh_server(3000, max_age_s=3600.0)


def test_fresh_server_accepts_a_new_one(monkeypatch):
    monkeypatch.setattr(cd.hygiene, "server_age_s", lambda port: 30.0)
    assert cd.require_fresh_server(3000, max_age_s=3600.0) == 30.0


def test_fresh_server_is_silent_when_no_server_found(monkeypatch):
    # Absent a server there is nothing to judge; the connect call will fail on its own.
    monkeypatch.setattr(cd.hygiene, "server_age_s", lambda port: None)
    assert cd.require_fresh_server(3000) is None


def test_sigterm_unwinds_so_finally_runs():
    cd.install_cleanup_handlers()
    cleaned = []
    try:
        try:
            signal.raise_signal(signal.SIGTERM)
        finally:
            cleaned.append("destroyed")
    except KeyboardInterrupt:
        pass
    assert cleaned == ["destroyed"], "SIGTERM must unwind, or actors outlive the process"
