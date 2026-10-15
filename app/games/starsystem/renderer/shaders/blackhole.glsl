#ifndef S2_BLACKHOLE_GLSL
#define S2_BLACKHOLE_GLSL

float schwarzschildRadius(float effectiveMass) {
    return max(sqrt(max(effectiveMass, 1.0)) * 0.08, 1.0);
}

float eventHorizonMask(float distanceToBlackHole, float eventRadius) {
    return 1.0 - smoothstep(eventRadius * 0.92, eventRadius, distanceToBlackHole);
}

vec2 bendPhotonNewtonian(vec2 position, vec2 direction, vec2 blackHole, float gravity, float dt) {
    vec2 delta = blackHole - position;
    float r2 = max(dot(delta, delta), 1.0);
    return normalize(direction + normalize(delta) * gravity / r2 * dt);
}

vec2 traceBentPhoton(vec2 origin, vec2 direction, vec2 blackHole, float gravity, float stepSize, int steps) {
    vec2 p = origin;
    vec2 dir = normalize(direction);
    for (int i = 0; i < steps; i++) {
        dir = bendPhotonNewtonian(p, dir, blackHole, gravity, stepSize);
        p += dir * stepSize;
    }
    return p;
}

vec3 accretionDiskColor(float normalizedRadius, float angle, float lensPower) {
    float band = smoothstep(1.0, 0.0, abs(normalizedRadius - 0.52));
    float hot = smoothstep(1.0, 0.05, normalizedRadius);
    float turbulence = 0.88 + sin(angle * 17.0 + normalizedRadius * 21.0) * 0.08;
    vec3 inner = vec3(5.8, 2.2, 0.28);
    vec3 outer = vec3(1.2, 0.14, 0.035);
    return mix(outer, inner, hot) * band * turbulence * max(lensPower, 0.0);
}

#endif
