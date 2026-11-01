"""앱 전용 경로로 가져오는 사운드보드 파일 목록."""
import json
import os
from pathlib import Path
import re
import uuid

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_ITEMS = 40
EXTENSIONS = {'.wav','.mp3','.ogg','.flac','.m4a','.aac','.opus'}
MIME_EXT = {'audio/wav':'.wav','audio/x-wav':'.wav','audio/mpeg':'.mp3','audio/ogg':'.ogg',
            'audio/flac':'.flac','audio/mp4':'.m4a','audio/aac':'.aac','audio/opus':'.opus'}


class AudioLibrary:
    def __init__(self, root):
        self.root = Path(root)
        self.index = self.root / 'library.json'
        self.items = []
        self.readable = True
        self.error = ''
        try:
            if self.index.stat().st_size > 131_072:
                raise ValueError()
            data = json.loads(self.index.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or data.get('version') != 1 or not isinstance(data.get('items'),list):
                raise ValueError()
            if len(data['items']) > MAX_ITEMS:
                raise ValueError()
            seen = set()
            for item in data['items']:
                key, extension = item['id'], item['extension']
                if (not isinstance(key,str) or not re.fullmatch('[0-9a-f]{32}',key) or key in seen
                    or extension not in EXTENSIONS or not isinstance(item['name'],str)
                    or not 0 < len(item['name']) <= 160
                    or type(item['bytes']) is not int or not 0 < item['bytes'] <= MAX_AUDIO_BYTES):
                    raise ValueError()
                seen.add(key)
            self.items = data['items']
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            self.readable = False
            self.error = '사운드 목록을 읽지 못해 파일 변경을 중단했습니다.'

    def staging_path(self):
        if not self.readable:
            raise ValueError(self.error)
        if len(self.items) >= MAX_ITEMS:
            raise ValueError(f'사운드는 {MAX_ITEMS}개까지 보관할 수 있습니다.')
        self.root.mkdir(parents=True,exist_ok=True)
        return self.root / ('.incoming-'+uuid.uuid4().hex)

    def _persist(self, items):
        temporary = self.index.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(dict(version=1,items=items),ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(temporary,self.index)
        finally:
            temporary.unlink(missing_ok=True)

    def commit_staging(self, staging, name, mime=''):
        staging = Path(staging)
        if staging.parent.resolve() != self.root.resolve() or not re.fullmatch(r'\.incoming-[0-9a-f]{32}',staging.name):
            raise ValueError('앱이 준비한 임시 파일만 등록할 수 있습니다.')
        if not self.readable or len(self.items) >= MAX_ITEMS:
            raise ValueError('목록 상태 또는 저장 개수를 확인해 주세요.')
        name = str(name).replace('\\','/').split('/')[-1].strip()[:160] or '가져온 사운드'
        name = ''.join(c if c.isprintable() else ' ' for c in name).strip() or '가져온 사운드'
        extension = Path(name).suffix.lower()
        if extension not in EXTENSIONS:
            extension = MIME_EXT.get(mime,'')
        if extension not in EXTENSIONS:
            raise ValueError('WAV·MP3·OGG·FLAC·M4A·AAC·OPUS 파일을 선택해 주세요.')
        size = staging.stat().st_size
        if not 0 < size <= MAX_AUDIO_BYTES:
            raise ValueError('비어 있지 않은 25MiB 이하의 오디오를 선택해 주세요.')
        item = dict(id=staging.name[len('.incoming-'):],name=name,extension=extension,bytes=size)
        target = self.root / (item['id']+extension)
        os.replace(staging,target)
        updated = [*self.items,item]
        try:
            self._persist(updated)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        self.items, self.error = updated, ''
        return item

    def import_file(self, source, cancelled=None):
        source = Path(source)
        staging = self.staging_path()
        try:
            if source.suffix.lower() not in EXTENSIONS:
                raise ValueError('지원하는 오디오 파일을 선택해 주세요.')
            total = 0
            with source.open('rb') as original, staging.open('xb') as target:
                while chunk := original.read(65536):
                    if cancelled and cancelled():
                        raise ValueError('가져오기를 취소했습니다.')
                    total += len(chunk)
                    if total > MAX_AUDIO_BYTES:
                        raise ValueError('오디오는 25MiB까지 가져올 수 있습니다.')
                    target.write(chunk)
            if cancelled and cancelled():
                raise ValueError('가져오기를 취소했습니다.')
            return self.commit_staging(staging,source.name)
        finally:
            staging.unlink(missing_ok=True)

    def path_for(self, key):
        item = next((item for item in self.items if item['id']==key),None)
        if item is None:
            raise ValueError('사운드 목록에서 파일을 선택해 주세요.')
        path = self.root / (item['id']+item['extension'])
        if path.is_symlink() or not path.is_file():
            raise ValueError('보관된 오디오가 없습니다. 원본을 다시 가져와 주세요.')
        return path

    def remove(self, key):
        if not self.readable:
            raise ValueError(self.error)
        item = next((item for item in self.items if item['id']==key),None)
        if item is None:
            raise ValueError('이미 제거된 사운드입니다.')
        path = self.root / (item['id']+item['extension'])
        quarantine = self.root / ('.removed-'+item['id'])
        moved = path.exists()
        if moved:
            os.replace(path,quarantine)
        updated = [row for row in self.items if row['id']!=key]
        try:
            self._persist(updated)
        except OSError:
            if moved:
                os.replace(quarantine,path)
            raise
        self.items = updated
        try:
            quarantine.unlink(missing_ok=True)
            self.error = ''
        except OSError:
            self.error = '목록에서 제거했습니다. 임시 파일의 정리는 나중에 필요합니다.'
