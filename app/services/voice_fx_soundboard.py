"""Non-destructive, cancellable batch copies using the shared Voice FX presets."""
from app.services.soundboard_audio import AudioDriver
from app.services.voice_fx import FXRenderer, check_cancel, validate_settings


def copy_with_fx(store, identities, settings, cancel, progress=None, renderer=None):
    settings = validate_settings(settings)
    if not identities or len(identities) != len(set(identities)):
        raise ValueError("변조할 사운드를 하나 이상 중복 없이 선택하세요.")
    items = {i["id"]: i for i in store.items()}
    if any(key not in items or not items[key]["path"] for key in identities):
        raise ValueError("선택한 사운드에 등록된 원본 파일이 없습니다.")
    renderer = renderer or FXRenderer()
    created = []
    try:
        for index, identity in enumerate(identities):
            check_cancel(cancel)
            item = items[identity]
            if progress:
                progress(f"변조 복사 {index + 1}/{len(identities)}: {item['title']}")
            rendered = renderer.render(store.resolve(item["path"]), settings, cancel, progress)
            check_cancel(cancel)
            new_id = store.add()
            created.append(new_id)
            store.rename(new_id, ("[FX] " + item["title"])[:100])
            store.register_file(new_id, rendered, lambda p: AudioDriver().validate(p, cancel), cancel)
        check_cancel(cancel)
        return created
    except BaseException:
        for identity in created:
            store.delete(identity)
        raise
