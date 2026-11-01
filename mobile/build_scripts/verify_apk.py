"""APK의 실행 구성·네이티브 라이브러리·실제 포함 리소스를 확인한다."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def android_tools(path, directory):
    directory = Path(directory)
    if str(directory)=='auto':
        root = Path.home()/'.buildozer/android/platform/android-sdk/build-tools'
        choices = [p for p in root.glob('*') if (p/'aapt').is_file() and (p/'apksigner').is_file()]
        require(bool(choices),'Android APK 검사 도구가 없습니다.')
        directory = max(choices,key=lambda p:tuple(int(n) for n in re.findall(r'\d+',p.name)))
    def command(tool, *args):
        if tool=='apksigner':
            executable = directory/'lib/apksigner.jar'
            require(executable.is_file(),'apksigner.jar가 없습니다.')
            invocation = ['java','-jar',str(executable)]
        else:
            executable = directory/tool
            if not executable.exists():
                executable = directory/(tool+'.exe')
            invocation = [str(executable)]
        result = subprocess.run([*invocation,*args,str(path)],check=True,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',timeout=60)
        return result.stdout
    badging = command('aapt','dump','badging')
    require("package: name='io.seoul2line.s2toolbox'" in badging,'Android 패키지명 불일치')
    require("sdkVersion:'26'" in badging,'최소 Android API 불일치')
    require("targetSdkVersion:'35'" in badging,'대상 Android API 불일치')
    require("application-label:'S2 Toolbox'" in badging,'앱 표시명 불일치')
    require("launchable-activity: name='org.kivy.android.PythonActivity'" in badging,'앱 실행 Activity 불일치')
    require('application-debuggable' in badging,'검사용 디버그 APK가 아님')
    signature = command('apksigner','verify','--verbose','--print-certs')
    require('Verifies' in signature,'APK 서명 검증 결과 누락')
    return dict(build_tools=directory.name,package='io.seoul2line.s2toolbox',min_api=26,target_api=35,
                debuggable=True,signature_verified=True)


def verify(path, tools=None):
    with zipfile.ZipFile(path) as apk:
        require(apk.testzip() is None,'APK ZIP 무결성 오류')
        names = set(apk.namelist())
        require('AndroidManifest.xml' in names,'AndroidManifest.xml 누락')
        dex = [n for n in names if n.endswith('.dex')]
        require(dex,'실행 DEX 누락')
        require(any(n.startswith('lib/arm64-v8a/') and 'libpython' in n for n in names),'arm64 Python 라이브러리 누락')
        for cls, message in [('SpeechBridge','TTS'),('AudioBridge','오디오'),('SystemBars','시스템 바')]:
            require(any(f'Lio/seoul2line/toolbox/{cls};'.encode() in apk.read(n) for n in dex),f'{message} Java 연결 코드 누락')
        with tarfile.open(fileobj=io.BytesIO(apk.read('assets/private.tar')), mode='r:*') as private:
            members = {n.name.lstrip('./'):n for n in private.getmembers() if n.isfile()}
            require(any(PurePosixPath(n).name in ('main.py','main.pyc') for n in members),'앱 진입점 누락')
            for relative in ('assets/NanumGothic-Regular.ttf','assets/toolbox-logo.png','assets/OFL.txt'):
                require(relative in members,f'{relative} 누락')
                expected = Path(__file__).resolve().parents[1] / relative
                actual = private.extractfile(members[relative]).read()
                require(hashlib.sha256(actual).digest() == hashlib.sha256(expected.read_bytes()).digest(),f'{relative} 불일치')
            forbidden = ('local_data/','tests/','.buildozer/','bin/')
            require(not any(n.startswith(forbidden) for n in members),'개발/개인 데이터가 APK에 포함됨')
            require(not any(PurePosixPath(n).name in ('scratchpad.txt','mobile-settings.json') for n in members),'개인 설정이 APK에 포함됨')
    native = android_tools(path,tools) if tools is not None else None
    return dict(apk=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size,
                android_tools_verified=native is not None,android=native,
                checks=['manifest','dex','arm64-python','speech-bridge','audio-bridge','system-bars','entrypoint','font','logo','license','no-user-data'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-tools',help='aapt/apksigner 디렉터리 또는 auto. 생략 시 ZIP/리소스 검사만 수행')
    parser.add_argument('--report',type=Path)
    parser.add_argument('apk',nargs='+',type=Path)
    args = parser.parse_args()
    reports = [verify(path,args.android_tools) for path in args.apk]
    if args.report:
        args.report.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(reports,ensure_ascii=False))
