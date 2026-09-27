using System;
using System.Collections.Generic;
using Unity.Collections;
using Unity.Jobs;
using UnityEngine;
using UnityEngine.Rendering;

namespace LJ.EnvironmentTools.Grass
{
    /// <summary>
    /// GPU-instanced stylized grass. Placement is generated deterministically from the settings
    /// below (only when they change or on explicit Regenerate), grouped into spatial chunks and
    /// drawn with Graphics.RenderMeshInstanced per camera. No GameObjects per blade and no
    /// per-blade CPU animation: wind runs entirely in the vertex shader.
    /// </summary>
    [ExecuteAlways]
    [DisallowMultipleComponent]
    [AddComponentMenu("LJ Environment Tools/Stylized Grass Renderer")]
    public sealed class StylizedGrassRenderer : MonoBehaviour
    {
        public enum DensityMapMode { RepeatPerTile, StretchAcrossArea }
        public enum DensityChannel { Red, Green, Blue, Alpha, Luminance }

        const int k_MaxInstancesPerDraw = 1023;

        // ---------------------------------------------------------------- Source
        [Tooltip("Prefab containing the blade mesh (MeshFilter) and material (MeshRenderer). Mesh pivot at root, local +Y up.")]
        public GameObject grassPrefab;
        [Tooltip("Optional. Replaces the prefab's material(s) when assigned.")]
        public Material materialOverride;

        // ---------------------------------------------------------------- Area & tiles
        [Tooltip("World size of one density tile (metres).")]
        [Min(0.1f)] public float tileSize = 8f;
        [Tooltip("Number of tiles along local X and Z.")]
        public Vector2Int tileCount = new Vector2Int(8, 8);
        [Tooltip("When on, the placement area is exactly Tile Size x Tile Count. When off, Area Size is used and tiles repeat from the area's -X/-Z corner.")]
        public bool areaFromTiles = true;
        [Tooltip("Placement area (local XZ, centred on this transform). Used only when Area From Tiles is off.")]
        public Vector2 areaSize = new Vector2(64f, 64f);

        // ---------------------------------------------------------------- Density
        [Tooltip("Maximum blades per square metre (at white in the density map, before the multiplier).")]
        [Min(0f)] public float density = 40f;
        [Tooltip("Overall multiplier on candidate count. Scales every area proportionally; black stays empty.")]
        [Min(0f)] public float densityMultiplier = 1f;
        [Tooltip("Grayscale density map (linear data: disable sRGB in the import settings). White = full, black = none.")]
        public Texture2D densityMap;
        public DensityChannel densityChannel = DensityChannel.Red;
        public DensityMapMode densityMapMode = DensityMapMode.RepeatPerTile;
        [Tooltip("Rotate the map by a deterministic multiple of 90 degrees per tile (RepeatPerTile only).")]
        public bool randomTileRotation = false;
        [Tooltip("Offset (wrap) the map by a deterministic amount per tile (RepeatPerTile only).")]
        public bool randomTileOffset = false;

        [Tooltip("Multiply map density by world-space procedural noise for natural patches.")]
        public bool useDensityNoise = true;
        [Min(0.0001f)] public float densityNoiseScale = 0.08f;
        [Range(0f, 1f)] public float densityNoiseStrength = 0.5f;
        [Range(0.01f, 0.5f)] public float densityNoiseSoftness = 0.25f;

        public int seed = 12345;

        // ---------------------------------------------------------------- Blades
        [Tooltip("Blade height range in metres.")]
        public Vector2 heightRange = new Vector2(0.35f, 0.75f);
        [Tooltip("Blade width range in metres.")]
        public Vector2 widthRange = new Vector2(0.05f, 0.09f);
        [Tooltip("0 = blades grow straight up, 1 = blades follow the ground normal.")]
        [Range(0f, 1f)] public float normalAlignment = 0.15f;
        [Tooltip("No grass on surfaces steeper than this.")]
        [Range(0f, 90f)] public float maxSlope = 55f;

        // ---------------------------------------------------------------- Ground
        [Tooltip("Layers that count as ground (Terrain and Mesh Colliders). Keep grass off other layers.")]
        public LayerMask groundLayers = 1;
        [Tooltip("Rays start this far above the placement plane (this transform's Y).")]
        [Min(0f)] public float raycastHeight = 50f;
        [Tooltip("Rays search this far below the placement plane.")]
        [Min(0f)] public float raycastDepth = 100f;

        // ---------------------------------------------------------------- Chunks & rendering
        [Min(1f)] public float chunkSize = 16f;
        [Tooltip("Chunks beyond this distance from the camera are not drawn. Blades shrink out over the last Fade Band metres.")]
        [Min(1f)] public float maxDrawDistance = 120f;
        [Min(0f)] public float fadeBand = 20f;
        public ShadowCastingMode shadowCasting = ShadowCastingMode.On;
        public bool receiveShadows = true;
        [Tooltip("Object motion vectors let HDRP's TAA/motion blur see wind animation.")]
        public bool motionVectors = true;
        [Tooltip("Extra padding added to chunk bounds (beyond blade height/width + wind).")]
        [Min(0f)] public float boundsPadding = 0.25f;
        [Tooltip("Safety cap on generated blades.")]
        [Min(1)] public int maxBlades = 2000000;

        [Tooltip("Regenerate automatically when placement settings or this transform change.")]
        public bool autoRegenerate = true;
        [Tooltip("Draw in Scene/Game view while not playing.")]
        public bool previewInEditMode = true;

        // ---------------------------------------------------------------- Generated (runtime only)
        public struct Chunk
        {
            public Bounds bounds;
            public int start;
            public int count;
        }

        Matrix4x4[] m_Matrices;
        Chunk[] m_Chunks;
        int m_BladeCount;
        bool m_Dirty = true;
        int m_GeneratedHash;
        Mesh m_Mesh;
        Material[] m_Materials;
        MaterialPropertyBlock m_Props;
        bool m_Subscribed;
        string m_LastError;

        public int BladeCount => m_BladeCount;
        public int ChunkCount => m_Chunks != null ? m_Chunks.Length : 0;
        public int LastVisibleChunks { get; private set; }
        public int LastCandidateCount { get; private set; }
        public float LastGenerationMs { get; private set; }
        public string LastError => m_LastError;
        public Chunk[] Chunks => m_Chunks;

        static readonly int s_BladeHeight = Shader.PropertyToID("_BladeHeight");
        static readonly int s_FadeCamera = Shader.PropertyToID("_GrassFadeCamera");
        static readonly int s_FadeRange = Shader.PropertyToID("_GrassFadeRange");

        // ================================================================ Lifecycle
        void OnEnable()
        {
            m_Dirty = true;
            if (!m_Subscribed)
            {
                RenderPipelineManager.beginContextRendering += OnBeginContextRendering;
                m_Subscribed = true;
            }
        }

        void OnDisable()
        {
            if (m_Subscribed)
            {
                RenderPipelineManager.beginContextRendering -= OnBeginContextRendering;
                m_Subscribed = false;
            }
            Clear();
        }

        void OnValidate()
        {
            heightRange.y = Mathf.Max(heightRange.x, heightRange.y);
            widthRange.y = Mathf.Max(widthRange.x, widthRange.y);
            tileCount = Vector2Int.Max(tileCount, Vector2Int.one);
            areaSize = Vector2.Max(areaSize, new Vector2(0.1f, 0.1f));
            fadeBand = Mathf.Min(fadeBand, maxDrawDistance);
            // Placement-relevant changes are detected by hash on the next render; render-only
            // settings (shadows, draw distance...) never trigger regeneration.
        }

        /// <summary>Marks placement dirty; it is rebuilt before the next frame is drawn.</summary>
        public void Regenerate()
        {
            m_Dirty = true;
            Generate();
        }

        /// <summary>Releases all generated placement data.</summary>
        public void Clear()
        {
            m_Matrices = null;
            m_Chunks = null;
            m_BladeCount = 0;
            m_Mesh = null;
            m_Materials = null;
            m_Dirty = true;
            LastVisibleChunks = 0;
        }

        // ================================================================ Area helpers
        public Vector2 EffectiveAreaSize => areaFromTiles ? new Vector2(tileSize * tileCount.x, tileSize * tileCount.y) : areaSize;
        public Vector2 AreaMinLocal => -EffectiveAreaSize * 0.5f;
        public Vector2Int EffectiveTileCount
        {
            get
            {
                if (areaFromTiles) return tileCount;
                var a = EffectiveAreaSize;
                return new Vector2Int(Mathf.Max(1, Mathf.CeilToInt(a.x / tileSize - 1e-4f)), Mathf.Max(1, Mathf.CeilToInt(a.y / tileSize - 1e-4f)));
            }
        }

        /// <summary>Density-map UV transform for a tile (rotation in 90 degree steps, offset). Public for the editor preview.</summary>
        public void GetTileUVTransform(int tx, int tz, out int rotationSteps, out Vector2 offset)
        {
            rotationSteps = 0;
            offset = Vector2.zero;
            if (densityMapMode != DensityMapMode.RepeatPerTile) return;
            uint h = GrassRandom.Hash(seed, tx, tz, 0x7A11E);
            if (randomTileRotation) rotationSteps = (int)(h & 3u);
            if (randomTileOffset)
            {
                var r = new GrassRandom(h ^ 0x9E3779B9u);
                offset = new Vector2(r.NextFloat(), r.NextFloat());
            }
        }

        /// <summary>Maps a point inside a tile (0..1) to density-map UV.</summary>
        public static Vector2 TileLocalToUV(Vector2 local, int rotationSteps, Vector2 offset)
        {
            Vector2 p = local - new Vector2(0.5f, 0.5f);
            switch (rotationSteps & 3)
            {
                case 1: p = new Vector2(-p.y, p.x); break;
                case 2: p = new Vector2(-p.x, -p.y); break;
                case 3: p = new Vector2(p.y, -p.x); break;
            }
            p += new Vector2(0.5f, 0.5f) + offset;
            return new Vector2(p.x - Mathf.Floor(p.x), p.y - Mathf.Floor(p.y));
        }

        // ================================================================ Hash of placement inputs
        int ComputePlacementHash()
        {
            var h = new HashBuilder();
            h.Add(grassPrefab ? grassPrefab.GetHashCode() : 0);
            h.Add(materialOverride ? materialOverride.GetHashCode() : 0);
            h.Add(tileSize); h.Add(tileCount.x); h.Add(tileCount.y); h.Add(areaFromTiles ? 1 : 0);
            h.Add(areaSize.x); h.Add(areaSize.y);
            h.Add(density); h.Add(densityMultiplier);
            h.Add(densityMap ? densityMap.GetHashCode() : 0);
#if UNITY_EDITOR
            h.Add(densityMap ? densityMap.imageContentsHash.GetHashCode() : 0);
#endif
            h.Add((int)densityChannel); h.Add((int)densityMapMode);
            h.Add(randomTileRotation ? 1 : 0); h.Add(randomTileOffset ? 1 : 0);
            h.Add(useDensityNoise ? 1 : 0); h.Add(densityNoiseScale); h.Add(densityNoiseStrength); h.Add(densityNoiseSoftness);
            h.Add(seed);
            h.Add(heightRange.x); h.Add(heightRange.y); h.Add(widthRange.x); h.Add(widthRange.y);
            h.Add(normalAlignment); h.Add(maxSlope);
            h.Add(groundLayers.value); h.Add(raycastHeight); h.Add(raycastDepth);
            h.Add(chunkSize); h.Add(boundsPadding); h.Add(maxBlades);
            var m = transform.localToWorldMatrix;
            for (int i = 0; i < 16; i++) h.Add(m[i]);
            return h.Value;
        }

        // ================================================================ Rendering
        void OnBeginContextRendering(ScriptableRenderContext context, List<Camera> cameras)
        {
            if (!isActiveAndEnabled) return;
            if (!Application.isPlaying && !previewInEditMode) return;

            if (m_Dirty || (autoRegenerate && ComputePlacementHash() != m_GeneratedHash))
                Generate();

            if (m_BladeCount == 0 || m_Mesh == null || m_Materials == null) return;

            if (m_Props == null) m_Props = new MaterialPropertyBlock();
            float meshHeight = Mathf.Max(m_Mesh.bounds.max.y, 1e-4f);
            float maxDist = maxDrawDistance;
            float maxDistSq = maxDist * maxDist;
            int visible = 0;

            for (int c = 0; c < cameras.Count; c++)
            {
                Camera cam = cameras[c];
                if (cam == null) continue;
                var type = cam.cameraType;
                if (type != CameraType.Game && type != CameraType.SceneView) continue;

                Vector3 camPos = cam.transform.position;
                m_Props.SetFloat(s_BladeHeight, meshHeight);
                m_Props.SetVector(s_FadeCamera, new Vector4(camPos.x, camPos.y, camPos.z, fadeBand > 0f ? 1f : 0f));
                m_Props.SetVector(s_FadeRange, new Vector4(maxDist - fadeBand, maxDist, 0f, 0f));

                for (int i = 0; i < m_Chunks.Length; i++)
                {
                    ref readonly Chunk chunk = ref m_Chunks[i];
                    // Distance limit here; frustum and shadow-caster culling is done by the
                    // pipeline from rp.worldBounds (so off-screen chunks can still cast shadows).
                    if (chunk.bounds.SqrDistance(camPos) > maxDistSq) continue;
                    visible++;

                    for (int s = 0; s < m_Materials.Length; s++)
                    {
                        Material mat = m_Materials[s];
                        if (mat == null) continue;
                        var rp = new RenderParams(mat)
                        {
                            camera = cam,
                            worldBounds = chunk.bounds,
                            shadowCastingMode = shadowCasting,
                            receiveShadows = receiveShadows,
                            layer = gameObject.layer,
                            motionVectorMode = motionVectors ? MotionVectorGenerationMode.Object : MotionVectorGenerationMode.Camera,
                            matProps = m_Props,
                        };
                        int submesh = Mathf.Min(s, m_Mesh.subMeshCount - 1);
                        for (int start = 0; start < chunk.count; start += k_MaxInstancesPerDraw)
                        {
                            int n = Mathf.Min(k_MaxInstancesPerDraw, chunk.count - start);
                            Graphics.RenderMeshInstanced(rp, m_Mesh, submesh, m_Matrices, n, chunk.start + start);
                        }
                    }
                }
            }
            LastVisibleChunks = visible;
        }

        // ================================================================ Generation
        bool ResolveSource(out Mesh mesh, out Material[] materials)
        {
            mesh = null;
            materials = null;
            if (grassPrefab == null) { m_LastError = "Assign a grass prefab."; return false; }
            var mf = grassPrefab.GetComponentInChildren<MeshFilter>(true);
            if (mf == null || mf.sharedMesh == null) { m_LastError = "The grass prefab has no MeshFilter with a mesh."; return false; }
            mesh = mf.sharedMesh;
            if (materialOverride != null)
            {
                materials = new Material[mesh.subMeshCount];
                for (int i = 0; i < materials.Length; i++) materials[i] = materialOverride;
            }
            else
            {
                var mr = mf.GetComponent<MeshRenderer>();
                if (mr == null || mr.sharedMaterial == null) { m_LastError = "The grass prefab has no MeshRenderer material."; return false; }
                materials = mr.sharedMaterials;
            }
            foreach (var m in materials)
            {
                if (m != null && !m.enableInstancing)
                {
                    m_LastError = "Material '" + m.name + "' must have Enable GPU Instancing turned on.";
                    return false;
                }
            }
            return true;
        }

        struct Candidate
        {
            public Vector3 origin;   // ray origin (world)
            public float yaw, height, width;
            public int chunk;
        }

        /// <summary>Builds placement data. Allocates only here, never per frame.</summary>
        public void Generate()
        {
            var sw = System.Diagnostics.Stopwatch.StartNew();
            m_Dirty = false;
            m_GeneratedHash = ComputePlacementHash();
            m_LastError = null;
            m_Matrices = null;
            m_Chunks = null;
            m_BladeCount = 0;
            LastCandidateCount = 0;

            if (!ResolveSource(out m_Mesh, out m_Materials)) { m_Mesh = null; m_Materials = null; return; }

            Bounds mb = m_Mesh.bounds;
            float meshHeight = Mathf.Max(mb.max.y, 1e-4f);
            float meshWidth = Mathf.Max(Mathf.Max(mb.size.x, mb.size.z), 1e-4f);

            float[] map = null; int mapW = 0, mapH = 0;
            if (densityMap != null && !DensityMapReader.Read(densityMap, densityChannel, out map, out mapW, out mapH, out string readError))
            {
                m_LastError = readError;
                return;
            }

            Vector2 area = EffectiveAreaSize;
            Vector2 areaMin = AreaMinLocal;
            Vector2Int tiles = EffectiveTileCount;
            int chunksX = Mathf.Max(1, Mathf.CeilToInt(area.x / chunkSize));
            int chunksZ = Mathf.Max(1, Mathf.CeilToInt(area.y / chunkSize));

            Matrix4x4 l2w = transform.localToWorldMatrix;
            Vector3 up = transform.up;
            float candidatesPerTileF = density * densityMultiplier * tileSize * tileSize;
            float noiseOffX = (seed & 0xFFFF) * 0.137f + 101.3f;
            float noiseOffZ = ((seed >> 16) & 0xFFFF) * 0.173f + 57.1f;

            var accepted = new List<Candidate>(Mathf.Min(maxBlades, 262144));
            long candidateCount = 0;

            for (int tz = 0; tz < tiles.y; tz++)
            {
                for (int tx = 0; tx < tiles.x; tx++)
                {
                    uint tileHash = GrassRandom.Hash(seed, tx, tz, 0xB1ADE);
                    var rng = new GrassRandom(tileHash);
                    // Fractional candidate counts resolved deterministically per tile.
                    int n = Mathf.FloorToInt(candidatesPerTileF);
                    if (rng.NextFloat() < candidatesPerTileF - n) n++;
                    GetTileUVTransform(tx, tz, out int rot, out Vector2 ofs);

                    Vector2 tileMin = areaMin + new Vector2(tx * tileSize, tz * tileSize);
                    for (int i = 0; i < n; i++)
                    {
                        // Draw every random value up front so each candidate's identity does not
                        // depend on density decisions (editing the map doesn't reshuffle blades).
                        float u = rng.NextFloat(), v = rng.NextFloat();
                        float accept = rng.NextFloat();
                        float yaw = rng.NextFloat() * 360f;
                        float hR = rng.NextFloat(), wR = rng.NextFloat();
                        candidateCount++;

                        Vector2 local = tileMin + new Vector2(u * tileSize, v * tileSize);
                        // Clip candidates of partial edge tiles (Area From Tiles off).
                        if (local.x > areaMin.x + area.x || local.y > areaMin.y + area.y) continue;

                        float p = 1f;
                        if (map != null)
                        {
                            Vector2 uv = densityMapMode == DensityMapMode.StretchAcrossArea
                                ? new Vector2((local.x - areaMin.x) / area.x, (local.y - areaMin.y) / area.y)
                                : TileLocalToUV(new Vector2(u, v), rot, ofs);
                            p = DensityMapReader.SampleBilinear(map, mapW, mapH, uv, densityMapMode == DensityMapMode.RepeatPerTile);
                        }
                        if (p <= 0f) continue; // black always empty

                        Vector3 worldFlat = l2w.MultiplyPoint3x4(new Vector3(local.x, 0f, local.y));
                        if (useDensityNoise && densityNoiseStrength > 0f)
                        {
                            float nz = Mathf.PerlinNoise(worldFlat.x * densityNoiseScale + noiseOffX, worldFlat.z * densityNoiseScale + noiseOffZ);
                            nz = SmoothStep(0.5f - densityNoiseSoftness, 0.5f + densityNoiseSoftness, nz);
                            p *= Mathf.Lerp(1f, nz, densityNoiseStrength);
                        }
                        if (accept >= p) continue;

                        int cx = Mathf.Clamp((int)((local.x - areaMin.x) / chunkSize), 0, chunksX - 1);
                        int cz = Mathf.Clamp((int)((local.y - areaMin.y) / chunkSize), 0, chunksZ - 1);
                        accepted.Add(new Candidate
                        {
                            origin = worldFlat + up * raycastHeight,
                            yaw = yaw,
                            height = Mathf.Lerp(heightRange.x, heightRange.y, hR),
                            width = Mathf.Lerp(widthRange.x, widthRange.y, wR),
                            chunk = cz * chunksX + cx,
                        });
                        if (accepted.Count >= maxBlades) break;
                    }
                    if (accepted.Count >= maxBlades) break;
                }
                if (accepted.Count >= maxBlades)
                {
                    m_LastError = "Max Blades (" + maxBlades + ") reached; placement truncated.";
                    break;
                }
            }
            LastCandidateCount = (int)Math.Min(candidateCount, int.MaxValue);

            if (accepted.Count == 0) { LastGenerationMs = (float)sw.Elapsed.TotalMilliseconds; return; }

            // ------------------------------------------------ Batched ground raycasts
            Physics.SyncTransforms();
            int count = accepted.Count;
            var commands = new NativeArray<RaycastCommand>(count, Allocator.TempJob, NativeArrayOptions.UninitializedMemory);
            var hits = new NativeArray<RaycastHit>(count, Allocator.TempJob, NativeArrayOptions.UninitializedMemory);
            var qp = new QueryParameters(groundLayers, false, QueryTriggerInteraction.Ignore, false);
            float rayLen = raycastHeight + raycastDepth;
            Vector3 down = -up;
            for (int i = 0; i < count; i++)
                commands[i] = new RaycastCommand(accepted[i].origin, down, qp, rayLen);

            var matrices = new Matrix4x4[count];
            var chunkOf = new int[count];
            int placed = 0;
            float minUpDot = Mathf.Cos(maxSlope * Mathf.Deg2Rad);
            try
            {
                RaycastCommand.ScheduleBatch(commands, hits, 256, 1).Complete();
                for (int i = 0; i < count; i++)
                {
                    RaycastHit hit = hits[i];
                    if (hit.collider == null) continue; // no ground: skip
                    float upDot = Vector3.Dot(hit.normal, up);
                    if (upDot < minUpDot) continue;

                    Candidate cd = accepted[i];
                    Vector3 bladeUp = Vector3.Slerp(up, hit.normal, normalAlignment).normalized;
                    Quaternion rot = Quaternion.FromToRotation(Vector3.up, bladeUp) * Quaternion.AngleAxis(cd.yaw, Vector3.up);
                    Vector3 scale = new Vector3(cd.width / meshWidth, cd.height / meshHeight, cd.width / meshWidth);
                    matrices[placed] = Matrix4x4.TRS(hit.point, rot, scale);
                    chunkOf[placed] = cd.chunk;
                    placed++;
                }
            }
            finally
            {
                commands.Dispose();
                hits.Dispose();
            }

            // ------------------------------------------------ Sort into chunks (counting sort)
            int chunkTotal = chunksX * chunksZ;
            var counts = new int[chunkTotal];
            for (int i = 0; i < placed; i++) counts[chunkOf[i]]++;
            var starts = new int[chunkTotal];
            int nonEmpty = 0;
            for (int c = 0, acc = 0; c < chunkTotal; c++) { starts[c] = acc; acc += counts[c]; if (counts[c] > 0) nonEmpty++; }
            var sorted = new Matrix4x4[placed];
            var cursor = (int[])starts.Clone();
            for (int i = 0; i < placed; i++) sorted[cursor[chunkOf[i]]++] = matrices[i];

            // Bounds: blade roots, then expanded by max blade height (vertical and horizontal,
            // covering the full wind bend) + blade width + padding.
            float padXZ = heightRange.y + widthRange.y + boundsPadding;
            float padY = heightRange.y + boundsPadding;
            var chunks = new Chunk[nonEmpty];
            int ci = 0;
            for (int c = 0; c < chunkTotal; c++)
            {
                if (counts[c] == 0) continue;
                int s = starts[c], e = s + counts[c];
                Vector3 mn = sorted[s].GetColumn(3), mx = mn;
                for (int i = s + 1; i < e; i++)
                {
                    Vector3 p = sorted[i].GetColumn(3);
                    mn = Vector3.Min(mn, p);
                    mx = Vector3.Max(mx, p);
                }
                mn -= new Vector3(padXZ, boundsPadding, padXZ);
                mx += new Vector3(padXZ, padY, padXZ);
                var b = new Bounds();
                b.SetMinMax(mn, mx);
                chunks[ci++] = new Chunk { bounds = b, start = s, count = counts[c] };
            }

            m_Matrices = sorted;
            m_Chunks = chunks;
            m_BladeCount = placed;
            LastGenerationMs = (float)sw.Elapsed.TotalMilliseconds;
        }

        static float SmoothStep(float a, float b, float x)
        {
            float t = Mathf.Clamp01((x - a) / Mathf.Max(b - a, 1e-5f));
            return t * t * (3f - 2f * t);
        }

        struct HashBuilder
        {
            int m_H;
            public int Value => m_H;
            public void Add(int v) { unchecked { m_H = (m_H * 31) ^ v; m_H = (int)((uint)m_H * 0x9E3779B1u); } }
            public void Add(float v) => Add(BitConverter.SingleToInt32Bits(v));
        }
    }

    /// <summary>Small deterministic PRNG (PCG-style hash stream). Identical on every platform.</summary>
    public struct GrassRandom
    {
        uint m_State;
        public GrassRandom(uint seed) { m_State = seed == 0 ? 0x6D2B79F5u : seed; }

        public static uint PCG(uint v)
        {
            unchecked
            {
                uint state = v * 747796405u + 2891336453u;
                uint word = ((state >> (int)((state >> 28) + 4u)) ^ state) * 277803737u;
                return (word >> 22) ^ word;
            }
        }

        public static uint Hash(int seed, int x, int z, uint salt)
        {
            unchecked { return PCG((uint)seed ^ PCG((uint)x + PCG((uint)z + PCG(salt)))); }
        }

        public uint NextUInt() { m_State = PCG(m_State); return m_State; }
        public float NextFloat() => (NextUInt() >> 8) * (1f / 16777216f);
    }

    /// <summary>Reads a density map once (at generation time) into a linear float array.</summary>
    public static class DensityMapReader
    {
        public static bool Read(Texture2D tex, StylizedGrassRenderer.DensityChannel channel, out float[] values, out int width, out int height, out string error)
        {
            values = null; width = tex.width; height = tex.height; error = null;
            Color32[] px = null;
            Texture2D tmp = null;
            RenderTexture rt = null;
            try
            {
                if (tex.isReadable)
                {
                    // Raw stored values: no sRGB conversion regardless of import settings.
                    px = tex.GetPixels32(0);
                }
                else
                {
                    // GPU copy into a linear render target. The sampler applies sRGB decoding if the
                    // texture is imported as sRGB, which is why density maps must have sRGB off.
                    rt = RenderTexture.GetTemporary(width, height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
                    Graphics.Blit(tex, rt);
                    var prev = RenderTexture.active;
                    RenderTexture.active = rt;
                    tmp = new Texture2D(width, height, TextureFormat.RGBA32, false, true);
                    tmp.ReadPixels(new Rect(0, 0, width, height), 0, 0, false);
                    tmp.Apply(false, false);
                    RenderTexture.active = prev;
                    px = tmp.GetPixels32(0);
                }
            }
            catch (Exception e)
            {
                error = "Could not read density map '" + tex.name + "': " + e.Message;
                return false;
            }
            finally
            {
                if (rt != null) RenderTexture.ReleaseTemporary(rt);
                if (tmp != null)
                {
                    if (Application.isPlaying) UnityEngine.Object.Destroy(tmp);
                    else UnityEngine.Object.DestroyImmediate(tmp);
                }
            }

            values = new float[px.Length];
            const float inv = 1f / 255f;
            for (int i = 0; i < px.Length; i++)
            {
                Color32 c = px[i];
                switch (channel)
                {
                    case StylizedGrassRenderer.DensityChannel.Red: values[i] = c.r * inv; break;
                    case StylizedGrassRenderer.DensityChannel.Green: values[i] = c.g * inv; break;
                    case StylizedGrassRenderer.DensityChannel.Blue: values[i] = c.b * inv; break;
                    case StylizedGrassRenderer.DensityChannel.Alpha: values[i] = c.a * inv; break;
                    default: values[i] = (c.r * 0.2126f + c.g * 0.7152f + c.b * 0.0722f) * inv; break;
                }
                // Snap near-black to exactly zero so compression noise cannot leak blades.
                if (values[i] < 0.5f * inv) values[i] = 0f;
            }
            return true;
        }

        /// <summary>Bilinear sample; UV (0,0) = bottom-left texel (Unity texture convention).</summary>
        public static float SampleBilinear(float[] data, int w, int h, Vector2 uv, bool wrap)
        {
            float x = uv.x * w - 0.5f, y = uv.y * h - 0.5f;
            int x0 = Mathf.FloorToInt(x), y0 = Mathf.FloorToInt(y);
            float fx = x - x0, fy = y - y0;
            int x1 = x0 + 1, y1 = y0 + 1;
            if (wrap)
            {
                x0 = Mod(x0, w); x1 = Mod(x1, w); y0 = Mod(y0, h); y1 = Mod(y1, h);
            }
            else
            {
                x0 = Mathf.Clamp(x0, 0, w - 1); x1 = Mathf.Clamp(x1, 0, w - 1);
                y0 = Mathf.Clamp(y0, 0, h - 1); y1 = Mathf.Clamp(y1, 0, h - 1);
            }
            float a = data[y0 * w + x0], b = data[y0 * w + x1], c = data[y1 * w + x0], d = data[y1 * w + x1];
            // Any black texel in the footprint of a fully black region stays black.
            return Mathf.Lerp(Mathf.Lerp(a, b, fx), Mathf.Lerp(c, d, fx), fy);
        }

        static int Mod(int a, int m) { int r = a % m; return r < 0 ? r + m : r; }
    }
}
