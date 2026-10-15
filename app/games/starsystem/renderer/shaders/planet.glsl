#ifndef S2_PLANET_GLSL
#define S2_PLANET_GLSL

vec3 lambertPlanet(vec3 albedo, vec3 starColor, vec2 normal, vec2 lightDir, float lightAmount) {
    float ndotl = max(dot(normalize(normal), normalize(lightDir)), 0.0);
    vec3 ambient = albedo * 0.035;
    vec3 diffuse = albedo * starColor * ndotl * lightAmount;
    float limb = pow(1.0 - abs(normal.x), 0.8) * 0.04;
    return ambient + diffuse + albedo * limb;
}

vec3 planetTerminator(vec3 nightColor, vec3 dayColor, vec2 normal, vec2 lightDir) {
    float shade = smoothstep(-0.18, 0.45, dot(normalize(normal), normalize(lightDir)));
    return mix(nightColor, dayColor, shade);
}

#endif
