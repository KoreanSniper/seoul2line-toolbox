"""Small offline ONNX/SDK packaging probe; does not download speech models."""
from importlib.metadata import version


def probe():
    import numpy as np
    import onnxruntime as ort
    from onnxruntime.datasets import get_example
    from supertonic import TTS
    from app.services.natural_tts import NeuralModel, voice_records

    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    session = ort.InferenceSession(get_example("mul_1.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    samples = np.arange(6, dtype=np.float32).reshape(3, 2)
    np.testing.assert_array_equal(session.run(None, {"X": samples})[0], samples * (samples + 1))
    assert callable(TTS.synthesize)
    model = NeuralModel()
    assert len(model.manifest["files"]) == 17 and len(voice_records()) == 10
    return {"supertonic": version("supertonic"), "onnxruntime": ort.__version__, "voices": 10, "cpu_inference": True}
