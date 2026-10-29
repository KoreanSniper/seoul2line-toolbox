"""Audio-free runtime probe used by source and frozen release checks."""
from pathlib import Path
import tempfile


def probe():
    import numpy as np
    import pedalboard
    import soundfile as sf
    from app.services.voice_fx import FXRenderer, builtin_presets
    from app.services.voice_fx_store import PresetStore

    with tempfile.TemporaryDirectory(prefix="toolbox-voice-fx-probe-") as folder:
        root = Path(folder)
        source = root / "source.wav"
        samples = (.15 * np.sin(2 * np.pi * 220 * np.arange(11025) / 22050)).astype(np.float32)
        sf.write(source, samples, 22050)
        renderer = FXRenderer(root / "cache")
        store = PresetStore(root / "presets")
        for preset in builtin_presets():
            output = renderer.render(source, preset["settings"])
            data, rate = sf.read(output)
            assert rate == 22050 and len(data) > 0 and np.isfinite(data).all()
        record = store.save("배포 검사", builtin_presets()[3]["settings"])
        store.export(root / "preset.json", record)
        assert store.import_file(root / "preset.json")[0]["settings"] == record["settings"]
        return {"pedalboard": pedalboard.__version__, "presets": len(builtin_presets()), "rate": 22050}
