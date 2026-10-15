#ifndef S2_STAR_GLSL
#define S2_STAR_GLSL

float inverseSquareLight(float luminosity, float distanceWorld) {
    float d = max(distanceWorld, 1.0);
    return luminosity / (d * d);
}

vec3 blackBodyApprox(float kelvin) {
    float t = clamp(kelvin, 1000.0, 40000.0) / 100.0;
    float r;
    float g;
    float b;

    if (t <= 66.0) {
        r = 1.0;
        g = clamp((99.4708025861 * log(t) - 161.1195681661) / 255.0, 0.0, 1.0);
        b = t <= 19.0 ? 0.0 : clamp((138.5177312231 * log(t - 10.0) - 305.0447927307) / 255.0, 0.0, 1.0);
    } else {
        r = clamp((329.698727446 * pow(t - 60.0, -0.1332047592)) / 255.0, 0.0, 1.0);
        g = clamp((288.1221695283 * pow(t - 60.0, -0.0755148492)) / 255.0, 0.0, 1.0);
        b = 1.0;
    }

    return vec3(r, g, b);
}

vec3 starDiscHdr(vec2 local, float radiusPx, float temperature, float luminosity) {
    float d = length(local);
    float core = 1.0 - smoothstep(radiusPx * 0.08, radiusPx, d);
    float corona = 1.0 - smoothstep(radiusPx, radiusPx * 5.8, d);
    vec3 color = blackBodyApprox(temperature);
    return color * (core * luminosity * 0.00035 + corona * luminosity * 0.000035);
}

#endif
