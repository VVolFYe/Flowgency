"""Independent computer-vision package: JamCam clip replay -> contract-A observations.

Pure modules (``counting``, ``config``, ``clips`` timestamp parsing, ``observation``)
import no CV stack; ``detect_track``, ``view_check``, and the CLI need the
dependencies in ``backend/requirements-vision.txt``. Vision never calls SUMO
and never controls signals.
"""
