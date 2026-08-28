"""D-2: the vehicle-command choke point.

`vehicle.apply_control()` is fire-and-forget. It returns once the message is written,
and whether the server has registered it before it processes the next `world.tick()` is
a wall-clock race. Synchronous mode does not close this, because it synchronises the
TICK, not the command queue feeding it.

The race is silent while a command is unchanged -- a late arrival re-applies the same
value -- so it only ever bites on the step where the command CHANGES, which in a
closed-loop run is every step. That is why divergence always appears to begin mid-run
for no reason, and why it survived every other determinism setting being pinned
correctly.

Measured open loop with the feedback cut and an identical scripted command sequence, it
moved the vehicle up to 60 m apart across three repetitions of one run, and the
applied-control READBACK differed between reps at the same step. With the acknowledged
batch command, pose, velocity, gear and applied control are bit-identical at every step.

Usage -- bind the client once at connect, then call apply_control everywhere:

    import carla_determinism as cd
    client = carla.Client(host, port); cd.bind_client(client)
    ...
    cd.apply_control(vehicle, carla.VehicleControl(throttle=t, brake=b, steer=s))
"""
_CLIENT = None


def bind_client(client):
    """Register the client used for acknowledged commands. Call once, at connect.

    A module-level handle rather than a threaded-through argument: one client per port
    is already a hard invariant (D-6), so it cannot be ambiguous, and threading a client
    into every driving loop in every study touches far more code than the fix itself.
    """
    global _CLIENT
    _CLIENT = client
    return client


def get_client():
    return _CLIENT


def apply_control(vehicle, control, enabled=True):
    """Apply a vehicle command without the RPC/tick race (D-2).

    `enabled=False` falls back to the fire-and-forget path deliberately, so a study that
    must keep reproducing a previously published result byte-for-byte can do so from the
    same code. It is not a performance option and it is not a default.
    """
    if enabled and _CLIENT is not None:
        import carla
        _CLIENT.apply_batch_sync(
            [carla.command.ApplyVehicleControl(vehicle.id, control)], False)
    else:
        vehicle.apply_control(control)
