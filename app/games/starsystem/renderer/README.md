# Star System Renderer Pipeline

목표 구조는 Pygame을 창/입력/상태 관리 껍데기로 두고, 우주 표현과 빛 계산을 OpenGL 렌더러로 옮기는 것이다.

현재 적용된 단계:

- 무한 월드 카메라: pan, zoom, world/screen 변환
- 절차적 별 배경: 카메라 위치와 무관하게 이어지는 무한 배경
- 항성 물성: 질량, 반지름, 표면온도, 광도
- 흑체색 LUT: 온도 기반 항성 색
- 역제곱 광량: 행성 조명 계산
- 대기 표현: 항성 방향에 맞춘 Rayleigh/Mie 스타일 테두리 산란
- 블랙홀 표현: 사건의 지평선/광자구 근사값, 강착원반, 뉴턴식 광선 굴절 경로
- ACES 톤매핑 헬퍼: 셰이더 이전 CPU-side 기준 구현
- 셰이더 소스 구조: tonemap, star, planet, atmosphere, bloom, blackhole 계산식 분리
- 풀스크린 셰이더 패스: fullscreen.vert, postprocess.frag, blackhole_ray.frag
- 폭발 셰이더 정리: explosion_fragment.frag로 이름과 입출력 통일
- Python 셰이더 로더: #include 해석과 PyOpenGL 컴파일/링크 유틸
- 런타임 GPU 패스: blackhole_ray.frag가 배경 별, 블랙홀 렌즈, 강착원반을 fragment shader에서 처리
- GPU 격자 패스: Pygame 카메라와 같은 좌표계로 배경/격자/블랙홀 왜곡을 계산
- CPU fallback: 셰이더 컴파일 실패 시 기존 별 배경/블랙홀 광자선 렌더로 대체
- 인게임 컨트롤 패널: 별도 Tk 조작창 대신 Pygame OpenGL 창 내부에서 버튼/슬라이더 처리
- GPU 충돌 폭발: 행성/먼지/파편 충돌의 섬광, 증기, 파편, 충격 방향을 explosion_fragment.frag에서 처리

다음 단계:

- 행성/항성 원형 렌더를 ShaderProgram 패스로 교체
- HDR framebuffer
- star/planet fragment shader 연결
- bloom pass 연결
- exposure/tone mapping pass 연결
- compute shader 기반 블랙홀 광선 적분
