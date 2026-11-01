"""APK의 실행 구성·네이티브 라이브러리·실제 포함 리소스를 확인한다."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


def verify(path):
    with zipfile.ZipFile(path) as apk:
        assert apk.testzip() is None, 'APK ZIP 무결성 오류'
        names = set(apk.namelist())
        assert 'AndroidManifest.xml' in names, 'AndroidManifest.xml 누락'
        dex = [n for n in names if n.endswith('.dex')]
        assert dex, '실행 DEX 누락'
        assert any(n.startswith('lib/arm64-v8a/') and 'libpython' in n for n in names), 'arm64 Python 라이브러리 누락'
        assert any(b'Lio/seoul2line/toolbox/SpeechBridge;' in apk.read(n) for n in dex), 'TTS Java 연결 코드 누락'
        assert any(b'Lio/seoul2line/toolbox/AudioBridge;' in apk.read(n) for n in dex), '오디오 Java 연결 코드 누락'
        with tarfile.open(fileobj=io.BytesIO(apk.read('assets/private.tar')), mode='r:*') as private:
            members = {n.name.lstrip('./'):n for n in private.getmembers() if n.isfile()}
            assert any(PurePosixPath(n).name in ('main.py','main.pyc') for n in members), '앱 진입점 누락'
            for relative in ('assets/NanumGothic-Regular.ttf','assets/toolbox-logo.png','assets/OFL.txt'):
                assert relative in members, f'{relative} 누락'
                expected = Path(__file__).resolve().parents[1] / relative
                actual = private.extractfile(members[relative]).read()
                assert hashlib.sha256(actual).digest() == hashlib.sha256(expected.read_bytes()).digest(), f'{relative} 불일치'
            forbidden = ('local_data/','tests/','.buildozer/','bin/')
            assert not any(n.startswith(forbidden) for n in members), '개발/개인 데이터가 APK에 포함됨'
            assert not any(PurePosixPath(n).name in ('scratchpad.txt','mobile-settings.json') for n in members), '개인 설정이 APK에 포함됨'
    return dict(apk=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size,
                checks=['manifest','dex','arm64-python','speech-bridge','entrypoint','font','logo','license','no-user-data'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk',nargs='+',type=Path)
    for path in parser.parse_args().apk:
        print(json.dumps(verify(path),ensure_ascii=False))
