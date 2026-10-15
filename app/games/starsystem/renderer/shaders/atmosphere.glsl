#ifndef S2_ATMOSPHERE_GLSL
#define S2_ATMOSPHERE_GLSL

vec3 rayleighMieAtmosphere(vec3 starColor, float lightAmount, float viewRim) {
    vec3 rayleigh = mix(starColor, vec3(0.22, 0.74, 0.97), 0.76);
    vec3 mie = mix(starColor, vec3(0.99, 0.82, 0.46), 0.38);
    float rim = smoothstep(0.08, 1.0, viewRim);
    float forwardScatter = pow(max(lightAmount, 0.0), 0.55);
    return rayleigh * rim * (0.12 + forwardScatter * 0.38) + mie * rim * forwardScatter * 0.24;
}

float atmosphereAlpha(float planetDistance, float radiusPx, float atmosphereRadiusPx) {
    float inner = smoothstep(radiusPx * 0.92, radiusPx * 1.04, planetDistance);
    float outer = 1.0 - smoothstep(radiusPx * 1.04, atmosphereRadiusPx, planetDistance);
    return clamp(inner * outer, 0.0, 1.0);
}

#endif
