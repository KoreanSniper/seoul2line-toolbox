"""네트워크와 PC 앱에 의존하지 않는 모바일 도구."""
import base64
import binascii
import json
import os
from pathlib import Path
import re
import shutil

MAX_TEXT = 32_768
MAX_NOTE = 200_000
BASES = (2, 8, 10, 16)


def _check_text(text):
    if len(text) > MAX_TEXT:
        raise ValueError(f'변환 입력은 {MAX_TEXT:,}자까지 지원합니다.')


def format_json(text, compact=False):
    _check_text(text)
    class Number(str):
        pass
    def invalid_constant(_):
        raise ValueError('NaN과 Infinity는 JSON 값으로 사용할 수 없습니다.')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('중복 키가 있는 JSON은 값이 손실될 수 있어 변환하지 않습니다.')
            result[key] = value
        return result
    try:
        data = json.loads(text, parse_constant=invalid_constant, parse_int=Number,
                          parse_float=Number, object_pairs_hook=unique_object)
    except json.JSONDecodeError as exc:
        raise ValueError(f'JSON {exc.lineno}행 {exc.colno}열을 확인해 주세요.') from exc
    except (RecursionError, OverflowError) as exc:
        raise ValueError('JSON의 중첩 깊이 또는 숫자 크기를 줄여 주세요.') from exc
    stack = [(data, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > 64:
            raise ValueError('JSON은 중첩 64단계까지 지원합니다.')
        if isinstance(value, (dict, list)):
            stack.extend((child, depth+1) for child in (value.values() if isinstance(value,dict) else value))
    def string(value):
        return json.dumps(value, ensure_ascii=False).encode('utf-8', errors='backslashreplace').decode('utf-8')
    def encode(value, depth=0):
        # 숫자 토큰을 부동소수점으로 바꾸지 않아 긴 소수·지수·큰 정수를 보존한다.
        if isinstance(value, Number):
            return str(value)
        if isinstance(value, (dict, list)):
            is_object = isinstance(value, dict)
            opening, closing = ('{','}') if is_object else ('[',']')
            if not value:
                return opening+closing
            items = [string(k)+(':' if compact else ': ')+encode(v,depth+1)
                     for k,v in value.items()] if is_object else [encode(v,depth+1) for v in value]
            if compact:
                return opening+','.join(items)+closing
            return opening+'\n'+'  '*(depth+1)+(',\n'+'  '*(depth+1)).join(items)+'\n'+'  '*depth+closing
        return string(value)
    result = encode(data)
    if len(result) > 262_144:
        raise ValueError('변환 결과가 너무 큽니다. 입력 크기 또는 중첩 깊이를 줄여 주세요.')
    return result


def encode_base64(text):
    _check_text(text)
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


def decode_base64(text):
    _check_text(text)
    try:
        return base64.b64decode(''.join(text.split()), validate=True).decode('utf-8')
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise ValueError('올바른 UTF-8 텍스트의 Base64 값을 입력해 주세요.') from exc


def convert_base(text, source=10, target=16):
    if source not in BASES or target not in BASES:
        raise ValueError('2·8·10·16진수만 지원합니다.')
    text = text.strip()
    if not text:
        raise ValueError('변환할 정수를 입력해 주세요.')
    sign = ''
    if text[0] in '+-':
        sign, text = text[0], text[1:]
    prefix = {2:'0b', 8:'0o', 16:'0x'}.get(source)
    if prefix and text.lower().startswith(prefix):
        text = text[2:]
    digits = {2:r'[01]+', 8:r'[0-7]+', 10:r'[0-9]+', 16:r'[0-9a-fA-F]+'}
    if len(text) > 1024:
        raise ValueError('정수는 1,024자리까지 지원합니다.')
    if not re.fullmatch(digits[source], text):
        raise ValueError(f'{source}진수에 사용할 수 없는 문자가 있습니다.')
    value = int(sign+text, source)
    return format(value, {2:'b', 8:'o', 10:'d', 16:'X'}[target])


class Scratchpad:
    """원자 저장과 이전 저장본 복구를 제공하는 단일 로컬 메모."""
    def __init__(self, path):
        self.path = Path(path)
        self.backup = self.path.with_suffix('.previous.txt')
        self.text = ''
        self.error = ''
        self.loaded = False
        self.load()

    def _read(self, path):
        # 손상 파일을 무제한 읽지 않는다. UTF-8 최대 크기를 기준으로 제한한다.
        if path.stat().st_size > MAX_NOTE * 4:
            raise ValueError('메모 크기 제한 초과')
        text = path.read_text(encoding='utf-8')
        if len(text) > MAX_NOTE:
            raise ValueError('메모 크기 제한 초과')
        return text

    def load(self):
        try:
            self.text = self._read(self.path)
            self.loaded = True
        except FileNotFoundError:
            self.loaded = True
        except (OSError, ValueError):
            self.error = '메모를 읽지 못했습니다. 이전 저장본 복구를 시도할 수 있어요.'

    def save(self, text):
        if not self.loaded:
            self.error = '기존 메모를 읽지 못해 덮어쓰지 않았습니다. 먼저 복구해 주세요.'
            return False
        if len(text) > MAX_NOTE:
            self.error = f'메모는 {MAX_NOTE:,}자까지 저장할 수 있습니다.'
            return False
        if text == self.text and self.path.exists():
            self.error = ''
            return True
        temporary = self.path.with_suffix('.tmp')
        backup_tmp = self.backup.with_suffix('.tmp')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(text, encoding='utf-8')
            if self.path.exists():
                shutil.copyfile(self.path, backup_tmp)
                os.replace(backup_tmp, self.backup)
            os.replace(temporary, self.path)
            self.text, self.error = text, ''
            return True
        except OSError:
            self.error = '메모 저장에 실패했습니다. 저장 공간을 확인해 주세요.'
            return False
        finally:
            for leftover in (temporary, backup_tmp):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    pass

    def restore_previous(self):
        try:
            text = self._read(self.backup)
            temporary = self.path.with_suffix('.restore.tmp')
            temporary.write_text(text, encoding='utf-8')
            # 원래 파일이 손상되어도 보존한다. 복구본은 백업을 교체하지 않는다.
            if self.path.exists():
                damaged = self.path.with_suffix('.before-restore.txt')
                shutil.copyfile(self.path, damaged)
            os.replace(temporary, self.path)
            self.text, self.error, self.loaded = text, '', True
            return text
        except (OSError, ValueError):
            self.error = '이전 저장본을 복구하지 못했습니다. 현재 메모는 유지됩니다.'
            return None
