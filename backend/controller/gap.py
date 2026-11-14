"""Decide whether the current green has a gap and competing traffic is near."""

def has_service_gap(state, observations):
    competing = False
    for vehicle in observations:
        signal = state[int(vehicle["link_index"])]
        distance = float(vehicle["distance_m"])
        speed = float(vehicle["speed_mps"])
        if signal in "Gg" and distance <= max(15, speed * 4):
            return False
        if signal in "rR" and distance <= max(25, speed * 4):
            competing = True
    return competing
