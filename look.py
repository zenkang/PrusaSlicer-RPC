

def look(layer_height: float, infill: int) -> str:
    table = {
        (0.2,15): "default_0.2_15.ini",
        (0.2,100): "default_0.2_100.ini",
    }
    return table.get((layer_height, infill), "cfg.ini")