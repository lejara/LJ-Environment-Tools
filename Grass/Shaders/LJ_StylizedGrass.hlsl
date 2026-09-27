// LJ Stylized Grass - Shader Graph custom functions (HDRP 17 / Unity 6).
//
// Used by SG_StylizedGrass.shadergraph through two File-mode Custom Function nodes:
//   LJG_GrassVertex : world-space wind bend + distance shrink (vertex stage, every HDRP pass)
//   LJG_GrassColor  : base/tip gradient, spatial colour variation, root occlusion (fragment stage)
//
// Conventions
//   * Blade mesh pivot at the root, local +Y up. Root-to-tip weight = positionOS.y / _BladeHeight
//     (_BladeHeight is written per draw by StylizedGrassRenderer from mesh.bounds.max.y).
//     Alternative: set "Height From UV" to 1 and author UV0.y = 0 at the root, 1 at the tip.
//   * Per-blade data (position, yaw, height, width) lives entirely in the instance matrix.
//     Per-blade randomness is hashed from the instance's absolute world root position, so every
//     pass (depth, shadow, GBuffer, forward, motion vectors) computes identical values.
//   * Time comes from the Shader Graph Time node, so HDRP's motion-vector pass re-evaluates the
//     vertex function with the previous frame's time and wind produces correct motion vectors.

#ifndef LJ_STYLIZED_GRASS_INCLUDED
#define LJ_STYLIZED_GRASS_INCLUDED

float LJG_Hash12(float2 p)
{
    float3 p3 = frac(float3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return frac((p3.x + p3.y) * p3.z);
}

float LJG_ValueNoise(float2 p)
{
    float2 i = floor(p);
    float2 f = frac(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    float a = LJG_Hash12(i);
    float b = LJG_Hash12(i + float2(1.0, 0.0));
    float c = LJG_Hash12(i + float2(0.0, 1.0));
    float d = LJG_Hash12(i + float2(1.0, 1.0));
    return lerp(lerp(a, b, u.x), lerp(c, d, u.x), u.y);
}

float LJG_Fbm(float2 p)
{
    return LJG_ValueNoise(p) * 0.65 + LJG_ValueNoise(p * 2.13 + 17.7) * 0.35;
}

#if defined(SHADERGRAPH_PREVIEW)
float3 LJG_InstanceRootAWS() { return float3(0.0, 0.0, 0.0); }
float3x3 LJG_ObjectToWorld3x3() { return float3x3(1, 0, 0, 0, 1, 0, 0, 0, 1); }
float3x3 LJG_WorldToObject3x3() { return float3x3(1, 0, 0, 0, 1, 0, 0, 0, 1); }
#else
// Translation of the (instanced) object-to-world matrix. HDRP's UNITY_MATRIX_M is camera
// relative, so convert back to absolute world space for stable noise and hashing.
float3 LJG_InstanceRootAWS()
{
    float3 rootRWS = float3(UNITY_MATRIX_M._m03, UNITY_MATRIX_M._m13, UNITY_MATRIX_M._m23);
    return GetAbsolutePositionWS(rootRWS);
}
float3x3 LJG_ObjectToWorld3x3() { return (float3x3)UNITY_MATRIX_M; }
float3x3 LJG_WorldToObject3x3() { return (float3x3)UNITY_MATRIX_I_M; }
#endif

float LJG_RootWeight(float3 positionOS, float2 uv, float bladeHeight, float heightFromUV)
{
    float fromHeight = positionOS.y / max(bladeHeight, 1e-4);
    return saturate(lerp(fromHeight, uv.y, saturate(heightFromUV)));
}

// ---------------------------------------------------------------------------------------------
// Vertex: wind + distance fade
// ---------------------------------------------------------------------------------------------
void LJG_GrassVertex_float(
    float3 PositionOS, float3 NormalOS, float2 UV, float Time,
    float BladeHeight, float HeightFromUV,
    float2 WindDirection, float WindStrength, float WindSpeed, float WindNoiseScale,
    float WindVariation, float FlutterStrength, float BendExponent,
    float4 FadeCamera, float2 FadeRange,
    out float3 PositionOut, out float3 NormalOut)
{
    NormalOut = NormalOS;

    float w = LJG_RootWeight(PositionOS, UV, BladeHeight, HeightFromUV);
    float3 rootAWS = LJG_InstanceRootAWS();
    float3x3 o2w = LJG_ObjectToWorld3x3();

    // World-space blade height (instance Y scale already contains the random height).
    float scaleY = length(float3(o2w._m01, o2w._m11, o2w._m21));
    float bladeH = max(BladeHeight, 1e-4) * scaleY;
    float bladeRand = LJG_Hash12(rootAWS.xz * 1.37 + 11.1);

    float2 dir = WindDirection;
    float dirLen = length(dir);
    dir = dirLen > 1e-4 ? dir / dirLen : float2(1.0, 0.0);
    float2 perp = float2(-dir.y, dir.x);

    // Coherent gusts: noise sampled at the blade root in absolute world space, scrolling
    // downwind. Neighbouring blades (and neighbouring tiles/chunks) share the same field.
    float t = Time * WindSpeed;
    float2 gustUV = rootAWS.xz * WindNoiseScale - dir * t;
    float gust = LJG_Fbm(gustUV);
    float side = LJG_ValueNoise(rootAWS.xz * WindNoiseScale * 1.7 + perp * (t * 0.6) + 41.0) - 0.5;

    // Small per-blade variation: strength scale + phase-shifted flutter.
    float strengthVar = 1.0 + (bladeRand - 0.5) * 2.0 * WindVariation;
    float flutter = sin(Time * (WindSpeed * 5.0 + 2.0) + bladeRand * 6.2831853) * FlutterStrength;

    float along = WindStrength * strengthVar * (0.25 + 0.75 * gust) + flutter * WindStrength;
    float across = (side * 0.5 + flutter * 0.3) * WindStrength;
    float2 bend = dir * along + perp * across;

    float bendLen = length(bend);
    bend *= bendLen > 0.95 ? 0.95 / bendLen : 1.0;

    // Root stays anchored (w = 0); displacement grows toward the tip.
    float curve = pow(w, max(BendExponent, 0.01));
    float2 offH = bend * bladeH * curve;

    // Approximately preserve blade length: drop the vertex as it swings sideways.
    float hy = w * bladeH;
    float dy = sqrt(max(hy * hy - dot(offH, offH), 0.0)) - hy;

    float3 offsetOS = mul(LJG_WorldToObject3x3(), float3(offH.x, dy, offH.y));
    float3 pos = PositionOS + offsetOS;

    // Distance shrink toward the root. FadeCamera is set per camera draw by the renderer (not
    // _WorldSpaceCameraPos) so shadow and main passes agree.
    if (FadeCamera.w > 0.5)
    {
        float d = distance(rootAWS, FadeCamera.xyz);
        float s = saturate((FadeRange.y - d) / max(FadeRange.y - FadeRange.x, 1e-3));
        pos *= s;
    }

    PositionOut = pos;
}

void LJG_GrassVertex_half(
    half3 PositionOS, half3 NormalOS, half2 UV, half Time,
    half BladeHeight, half HeightFromUV,
    half2 WindDirection, half WindStrength, half WindSpeed, half WindNoiseScale,
    half WindVariation, half FlutterStrength, half BendExponent,
    half4 FadeCamera, half2 FadeRange,
    out half3 PositionOut, out half3 NormalOut)
{
    float3 p; float3 n;
    LJG_GrassVertex_float(PositionOS, NormalOS, UV, Time, BladeHeight, HeightFromUV,
        WindDirection, WindStrength, WindSpeed, WindNoiseScale, WindVariation, FlutterStrength,
        BendExponent, FadeCamera, FadeRange, p, n);
    PositionOut = p; NormalOut = n;
}

// ---------------------------------------------------------------------------------------------
// Fragment: colour
// ---------------------------------------------------------------------------------------------
void LJG_GrassColor_float(
    float3 PositionOS, float2 UV, UnityTexture2D BladeTexture,
    float BladeHeight, float HeightFromUV,
    float4 BaseColor, float4 TipColor, float GradientPower,
    float4 VariationColor, float ColorVariation, float ColorNoiseScale,
    float BrightnessVariation, float RootDarkening,
    out float3 Color, out float Alpha, out float Occlusion)
{
    float w = LJG_RootWeight(PositionOS, UV, BladeHeight, HeightFromUV);
    float3 rootAWS = LJG_InstanceRootAWS();

    float3 col = lerp(BaseColor.rgb, TipColor.rgb, pow(w, max(GradientPower, 0.01)));

    // Subtle, spatially coherent patches (world space, continuous across tiles).
    float patch = LJG_Fbm(rootAWS.xz * ColorNoiseScale);
    float3 varCol = VariationColor.rgb * lerp(0.6, 1.0, w);
    col = lerp(col, varCol, saturate(patch * ColorVariation));

    // Tiny per-blade brightness jitter.
    float bladeRand = LJG_Hash12(rootAWS.xz * 3.71 + 5.3);
    col *= 1.0 + (bladeRand - 0.5) * 2.0 * BrightnessVariation;

    float4 tex = SAMPLE_TEXTURE2D(BladeTexture.tex, BladeTexture.samplerstate, UV);
    Color = col * tex.rgb;
    Alpha = tex.a * BaseColor.a;
    Occlusion = lerp(1.0 - saturate(RootDarkening), 1.0, w);
}

void LJG_GrassColor_half(
    half3 PositionOS, half2 UV, UnityTexture2D BladeTexture,
    half BladeHeight, half HeightFromUV,
    half4 BaseColor, half4 TipColor, half GradientPower,
    half4 VariationColor, half ColorVariation, half ColorNoiseScale,
    half BrightnessVariation, half RootDarkening,
    out half3 Color, out half Alpha, out half Occlusion)
{
    float3 c; float a; float o;
    LJG_GrassColor_float(PositionOS, UV, BladeTexture, BladeHeight, HeightFromUV, BaseColor, TipColor,
        GradientPower, VariationColor, ColorVariation, ColorNoiseScale, BrightnessVariation,
        RootDarkening, c, a, o);
    Color = c; Alpha = a; Occlusion = o;
}

#endif // LJ_STYLIZED_GRASS_INCLUDED
