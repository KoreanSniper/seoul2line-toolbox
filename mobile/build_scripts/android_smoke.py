"""ADB로 디버그 APK를 실행하고 실제 Android 검사 보고서·화면을 수집한다."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

PACKAGE = 'io.seoul2line.s2toolbox'
ACTIVITY = 'org.kivy.android.PythonActivity'


def check(condition, message='Android 검사 보고서 조건 불일치'):
    if not condition:
        raise AssertionError(message)


def adb(*args, check=True, timeout=60):
    result = subprocess.run(['adb',*map(str,args)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8',errors='replace') or result.stdout.decode('utf-8',errors='replace'))
    return result


def wait_report(run, phase, timeout=180):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        result = adb('exec-out','run-as',PACKAGE,'cat',f'files/android-qa/{run}/phase-{phase}.json',check=False,timeout=10)
        if result.returncode == 0:
            try:
                report = json.loads(result.stdout)
                if report.get('status') != 'passed':
                    raise AssertionError(json.dumps(report,ensure_ascii=False))
                return report
            except json.JSONDecodeError:
                pass
        time.sleep(.5)
    raise TimeoutError(f'Android {phase}단계 보고서를 받지 못했습니다.')


def validate(report, phase):
    check(report.get('status')=='passed' and report.get('phase')==phase)
    checks = set(report.get('checks',[]))
    if phase == 1:
        required = {'android_home_five_tabs','three_themes','five_tab_bindings_and_back','personalization_saved',
                    'offline_converter','note_saved_on_navigation','android_local_audio_import','android_mediaplayer_completion'}
        check(required <= checks,f'Android 검사 누락: {required-checks}')
        check(checks & {'android_tts_catalogue','android_tts_no_offline_voice_handled'},'네이티브 TTS 응답 누락')
    else:
        check('real_process_restart_theme_pins_note_audio' in checks)
    check(report.get('width',0)>0 and report.get('height',0)>0,'Android 화면 크기 누락')


def run(apk, output, commit):
    output.mkdir(parents=True,exist_ok=True)
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    checksum_file = apk.parent/'SHA256SUMS.txt'
    if checksum_file.exists():
        rows = [line.split(maxsplit=1) for line in checksum_file.read_text().splitlines() if line.strip()]
        check(any(hash_==digest and Path(name.lstrip('*')).name==apk.name for hash_,name in rows),'빌드 APK 해시 불일치')
    run_id = uuid.uuid4().hex[:16]
    reports = []
    try:
        adb('wait-for-device')
        abi = adb('shell','getprop','ro.product.cpu.abilist').stdout.decode().strip()
        api = adb('shell','getprop','ro.build.version.sdk').stdout.decode().strip()
        check('arm64-v8a' in abi,f'이 에뮬레이터는 arm64 APK를 실행할 수 없습니다: {abi}')
        adb('logcat','-c')
        adb('install','-r',apk,timeout=120)
        for phase in (1,2):
            adb('shell','am','force-stop',PACKAGE)
            adb('shell','am','start','-W','-n',f'{PACKAGE}/{ACTIVITY}',
                '--ez','s2_smoke_test','true','--es','s2_smoke_run',run_id,'--ei','s2_smoke_phase',phase)
            report = wait_report(run_id,phase)
            validate(report,phase)
            reports.append(report)
            (output/f'phase-{phase}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            (output/f'android-screen-phase-{phase}.png').write_bytes(adb('exec-out','screencap','-p').stdout)
        for name in ('home-dark.png','home-light.png','home-green.png','tts-catalogue.png','home-final.png','home-restored.png'):
            result = adb('exec-out','run-as',PACKAGE,'cat',f'files/android-qa/{run_id}/{name}',check=False)
            if result.returncode == 0:
                (output/name).write_bytes(result.stdout)
        summary = dict(status='passed',apk=apk.name,sha256=digest,source_commit=commit,
                       android_api=api,device_abis=abi,reports=reports)
        (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False))
    finally:
        try:
            (output/'logcat.txt').write_bytes(adb('logcat','-d','-t','500',check=False,timeout=15).stdout)
        except (OSError,subprocess.TimeoutExpired):
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('mobile/local_data/android-emulator-report'))
    parser.add_argument('--commit',default='')
    args = parser.parse_args()
    run(args.apk,args.output,args.commit)
