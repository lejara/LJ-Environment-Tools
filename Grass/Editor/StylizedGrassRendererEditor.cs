using UnityEditor;
using UnityEngine;

namespace LJ.EnvironmentTools.Grass.Editor
{
    [CustomEditor(typeof(StylizedGrassRenderer))]
    public sealed class StylizedGrassRendererEditor : UnityEditor.Editor
    {
        static bool s_ShowSource = true, s_ShowArea = true, s_ShowDensity = true, s_ShowBlades = true,
                    s_ShowGround = true, s_ShowRender = true, s_ShowPreview = true;

        internal const string k_PrefTiles = "LJGrass.Gizmo.Tiles";
        internal const string k_PrefOrientation = "LJGrass.Gizmo.Orientation";
        internal const string k_PrefDensityDots = "LJGrass.Gizmo.DensityDots";
        internal const string k_PrefChunks = "LJGrass.Gizmo.Chunks";

        SerializedProperty P(string n) => serializedObject.FindProperty(n);

        public override void OnInspectorGUI()
        {
            var g = (StylizedGrassRenderer)target;
            serializedObject.Update();

            DrawButtons(g);
            DrawStatus(g);

            if (Section(ref s_ShowSource, "Source"))
            {
                EditorGUILayout.PropertyField(P("grassPrefab"));
                EditorGUILayout.PropertyField(P("materialOverride"));
                DrawSourceChecks(g);
            }

            if (Section(ref s_ShowArea, "Placement Area & Tiles"))
            {
                EditorGUILayout.PropertyField(P("tileSize"));
                EditorGUILayout.PropertyField(P("areaFromTiles"));
                using (new EditorGUI.DisabledScope(!g.areaFromTiles))
                    EditorGUILayout.PropertyField(P("tileCount"));
                using (new EditorGUI.DisabledScope(g.areaFromTiles))
                    EditorGUILayout.PropertyField(P("areaSize"));
                var a = g.EffectiveAreaSize; var t = g.EffectiveTileCount;
                EditorGUILayout.HelpBox($"Area {a.x:0.#} x {a.y:0.#} m, {t.x} x {t.y} tiles, centred on this transform (local XZ).", MessageType.None);
            }

            if (Section(ref s_ShowDensity, "Density"))
            {
                EditorGUILayout.PropertyField(P("density"), new GUIContent("Density (blades/m²)"));
                EditorGUILayout.PropertyField(P("densityMultiplier"));
                EditorGUILayout.PropertyField(P("seed"));
                EditorGUILayout.Space(2);
                EditorGUILayout.PropertyField(P("densityMap"));
                if (g.densityMap != null)
                {
                    EditorGUILayout.PropertyField(P("densityChannel"));
                    EditorGUILayout.PropertyField(P("densityMapMode"));
                    using (new EditorGUI.DisabledScope(g.densityMapMode != StylizedGrassRenderer.DensityMapMode.RepeatPerTile))
                    {
                        EditorGUILayout.PropertyField(P("randomTileRotation"));
                        EditorGUILayout.PropertyField(P("randomTileOffset"));
                    }
                    DrawDensityMapChecks(g.densityMap);
                }
                EditorGUILayout.Space(2);
                EditorGUILayout.PropertyField(P("useDensityNoise"));
                if (g.useDensityNoise)
                {
                    EditorGUI.indentLevel++;
                    EditorGUILayout.PropertyField(P("densityNoiseScale"), new GUIContent("Scale"));
                    EditorGUILayout.PropertyField(P("densityNoiseStrength"), new GUIContent("Strength"));
                    EditorGUILayout.PropertyField(P("densityNoiseSoftness"), new GUIContent("Softness"));
                    EditorGUI.indentLevel--;
                }
                float perTile = g.density * g.densityMultiplier * g.tileSize * g.tileSize;
                var tc = g.EffectiveTileCount;
                EditorGUILayout.HelpBox($"≈{perTile:N0} candidates per tile, ≈{perTile * tc.x * tc.y:N0} total at full (white) density.", MessageType.None);
            }

            if (Section(ref s_ShowBlades, "Blades"))
            {
                EditorGUILayout.PropertyField(P("heightRange"), new GUIContent("Height Range (m)"));
                EditorGUILayout.PropertyField(P("widthRange"), new GUIContent("Width Range (m)"));
                EditorGUILayout.PropertyField(P("normalAlignment"));
                EditorGUILayout.PropertyField(P("maxSlope"));
            }

            if (Section(ref s_ShowGround, "Ground"))
            {
                EditorGUILayout.PropertyField(P("groundLayers"));
                EditorGUILayout.PropertyField(P("raycastHeight"));
                EditorGUILayout.PropertyField(P("raycastDepth"));
                if (g.groundLayers.value == 0)
                    EditorGUILayout.HelpBox("Ground Layers is empty: no grass will be placed.", MessageType.Warning);
            }

            if (Section(ref s_ShowRender, "Chunks & Rendering"))
            {
                EditorGUILayout.PropertyField(P("chunkSize"));
                EditorGUILayout.PropertyField(P("maxDrawDistance"));
                EditorGUILayout.PropertyField(P("fadeBand"));
                EditorGUILayout.PropertyField(P("shadowCasting"));
                EditorGUILayout.PropertyField(P("receiveShadows"));
                EditorGUILayout.PropertyField(P("motionVectors"));
                EditorGUILayout.PropertyField(P("boundsPadding"));
                EditorGUILayout.PropertyField(P("maxBlades"));
            }

            if (Section(ref s_ShowPreview, "Editor Preview"))
            {
                EditorGUILayout.PropertyField(P("previewInEditMode"));
                EditorGUILayout.PropertyField(P("autoRegenerate"));
                PrefToggle("Show Tile Boundaries", k_PrefTiles, true);
                PrefToggle("Show Density Map Orientation", k_PrefOrientation, true);
                PrefToggle("Show Density Map Preview Dots", k_PrefDensityDots, false);
                PrefToggle("Show Chunk Bounds", k_PrefChunks, false);
                EditorGUILayout.HelpBox("For animated wind in the Scene view enable 'Always Refresh' in the Scene view effects menu.", MessageType.None);
            }

            if (serializedObject.ApplyModifiedProperties())
                SceneView.RepaintAll();
        }

        static bool Section(ref bool state, string title)
        {
            EditorGUILayout.Space(4);
            state = EditorGUILayout.BeginFoldoutHeaderGroup(state, title);
            EditorGUILayout.EndFoldoutHeaderGroup();
            return state;
        }

        static void PrefToggle(string label, string key, bool def)
        {
            bool v = EditorPrefs.GetBool(key, def);
            bool nv = EditorGUILayout.Toggle(label, v);
            if (nv != v) { EditorPrefs.SetBool(key, nv); SceneView.RepaintAll(); }
        }

        void DrawButtons(StylizedGrassRenderer g)
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button("Regenerate", GUILayout.Height(26)))
                {
                    foreach (var t in targets) ((StylizedGrassRenderer)t).Regenerate();
                    SceneView.RepaintAll();
                }
                if (GUILayout.Button("Clear", GUILayout.Height(26), GUILayout.Width(70)))
                {
                    foreach (var t in targets)
                    {
                        var r = (StylizedGrassRenderer)t;
                        Undo.RecordObject(r, "Clear Grass");
                        r.autoRegenerate = false;
                        r.Clear();
                        EditorUtility.SetDirty(r);
                    }
                    SceneView.RepaintAll();
                }
            }
        }

        static void DrawStatus(StylizedGrassRenderer g)
        {
            if (!string.IsNullOrEmpty(g.LastError))
                EditorGUILayout.HelpBox(g.LastError, MessageType.Warning);
            EditorGUILayout.HelpBox(
                $"Blades: {g.BladeCount:N0} of {g.LastCandidateCount:N0} candidates   Chunks: {g.ChunkCount} ({g.LastVisibleChunks} drawn last frame)\n" +
                $"Last generation: {g.LastGenerationMs:0.0} ms", MessageType.Info);
        }

        static void DrawSourceChecks(StylizedGrassRenderer g)
        {
            if (g.grassPrefab == null) return;
            var mf = g.grassPrefab.GetComponentInChildren<MeshFilter>(true);
            if (mf == null || mf.sharedMesh == null) return;
            var b = mf.sharedMesh.bounds;
            EditorGUILayout.HelpBox($"Mesh '{mf.sharedMesh.name}': {mf.sharedMesh.triangles.Length / 3} tris, height {b.max.y:0.###}, width {Mathf.Max(b.size.x, b.size.z):0.###} (local units).", MessageType.None);
            if (Mathf.Abs(b.min.y) > 0.02f * Mathf.Max(b.size.y, 1e-4f))
                EditorGUILayout.HelpBox("Mesh min Y is not at 0: the pivot should be at the blade root for correct anchoring.", MessageType.Warning);
            if (mf.transform != g.grassPrefab.transform && (mf.transform.localRotation != Quaternion.identity || mf.transform.localScale != Vector3.one))
                EditorGUILayout.HelpBox("The mesh's child transform is rotated/scaled inside the prefab. Transforms are ignored: bake them into the mesh so local +Y is up.", MessageType.Warning);

            Material[] mats = g.materialOverride != null ? new[] { g.materialOverride } : mf.GetComponent<MeshRenderer>()?.sharedMaterials;
            if (mats == null) return;
            foreach (var m in mats)
            {
                if (m == null || m.enableInstancing) continue;
                using (new EditorGUILayout.HorizontalScope())
                {
                    EditorGUILayout.HelpBox($"'{m.name}' needs GPU instancing.", MessageType.Error);
                    if (GUILayout.Button("Enable", GUILayout.Width(60), GUILayout.Height(38)))
                    {
                        Undo.RecordObject(m, "Enable GPU Instancing");
                        m.enableInstancing = true;
                        EditorUtility.SetDirty(m);
                        g.Regenerate();
                    }
                }
            }
        }

        static void DrawDensityMapChecks(Texture2D tex)
        {
            var path = AssetDatabase.GetAssetPath(tex);
            var imp = AssetImporter.GetAtPath(path) as TextureImporter;
            if (imp == null) return;
            bool srgb = imp.sRGBTexture;
            bool compressed = imp.textureCompression != TextureImporterCompression.Uncompressed;
            if (!srgb && !compressed) return;
            using (new EditorGUILayout.HorizontalScope())
            {
                string msg = srgb ? "Density map is imported as sRGB: gray values would be gamma-decoded. Density maps are linear data." : "Density map is compressed: gray levels may band or leak into black.";
                EditorGUILayout.HelpBox(msg, srgb ? MessageType.Warning : MessageType.Info);
                if (GUILayout.Button("Fix", GUILayout.Width(50), GUILayout.Height(38)))
                    DensityMapImport.Apply(imp);
            }
        }
    }

    /// <summary>Recommended import settings for grayscale density maps.</summary>
    public static class DensityMapImport
    {
        public static void Apply(TextureImporter imp)
        {
            imp.sRGBTexture = false;                                   // linear data
            imp.textureCompression = TextureImporterCompression.Uncompressed;
            imp.mipmapEnabled = false;                                 // sampled at mip 0 on the CPU
            imp.wrapMode = TextureWrapMode.Repeat;
            imp.isReadable = true;                                     // exact CPU read; GPU fallback exists
            imp.SaveAndReimport();
        }

        [MenuItem("Assets/LJ Environment Tools/Configure As Grass Density Map")]
        static void ConfigureSelected()
        {
            foreach (var o in Selection.objects)
                if (AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(o)) is TextureImporter imp)
                    Apply(imp);
        }

        [MenuItem("Assets/LJ Environment Tools/Configure As Grass Density Map", true)]
        static bool ConfigureSelectedValidate() => Selection.activeObject is Texture2D;
    }

    /// <summary>Scene-view gizmos: area, tiles, density-map orientation, optional density dots and chunk bounds.</summary>
    static class StylizedGrassGizmos
    {
        static readonly Color k_Area = new Color(0.55f, 1f, 0.35f, 0.9f);
        static readonly Color k_Tile = new Color(0.55f, 1f, 0.35f, 0.35f);
        static readonly Color k_U = new Color(1f, 0.3f, 0.25f, 0.95f);
        static readonly Color k_V = new Color(0.3f, 0.6f, 1f, 0.95f);

        static Texture2D s_CachedTex;
        static Hash128 s_CachedHash;
        static StylizedGrassRenderer.DensityChannel s_CachedChannel;
        static float[] s_Map; static int s_W, s_H;

        [DrawGizmo(GizmoType.Selected | GizmoType.Active)]
        static void Draw(StylizedGrassRenderer g, GizmoType type)
        {
            var area = g.EffectiveAreaSize;
            var min = g.AreaMinLocal;
            var tiles = g.EffectiveTileCount;
            float ts = g.tileSize;

            using (new Handles.DrawingScope(g.transform.localToWorldMatrix))
            {
                // Area outline
                Handles.color = k_Area;
                Vector3 a = L(min.x, min.y), b = L(min.x + area.x, min.y), c = L(min.x + area.x, min.y + area.y), d = L(min.x, min.y + area.y);
                Handles.DrawAAPolyLine(3f, a, b, c, d, a);

                // Tile boundaries
                if (EditorPrefs.GetBool(StylizedGrassRendererEditor.k_PrefTiles, true))
                {
                    Handles.color = k_Tile;
                    int maxLines = 128;
                    for (int x = 1; x < tiles.x && x < maxLines; x++)
                    {
                        float lx = Mathf.Min(min.x + x * ts, min.x + area.x);
                        Handles.DrawLine(L(lx, min.y), L(lx, min.y + area.y));
                    }
                    for (int z = 1; z < tiles.y && z < maxLines; z++)
                    {
                        float lz = Mathf.Min(min.y + z * ts, min.y + area.y);
                        Handles.DrawLine(L(min.x, lz), L(min.x + area.x, lz));
                    }
                }

                // Density-map orientation (U = red, V = blue), from the texture's (0,0) corner
                if (EditorPrefs.GetBool(StylizedGrassRendererEditor.k_PrefOrientation, true))
                {
                    if (g.densityMapMode == StylizedGrassRenderer.DensityMapMode.StretchAcrossArea || g.densityMap == null)
                    {
                        DrawUVAxes(min, area, 0, Vector2.zero, true);
                    }
                    else
                    {
                        int maxTiles = 1024, n = 0;
                        for (int z = 0; z < tiles.y; z++)
                            for (int x = 0; x < tiles.x; x++)
                            {
                                if (n++ > maxTiles) break;
                                g.GetTileUVTransform(x, z, out int rot, out Vector2 ofs);
                                DrawUVAxes(min + new Vector2(x * ts, z * ts), new Vector2(ts, ts), rot, ofs, x == 0 && z == 0);
                            }
                    }
                }

                // Density preview dots (sampled exactly as generation does, noise excluded)
                if (g.densityMap != null && EditorPrefs.GetBool(StylizedGrassRendererEditor.k_PrefDensityDots, false) && EnsureMap(g))
                {
                    int perTile = Mathf.Clamp(Mathf.FloorToInt(Mathf.Sqrt(6000f / Mathf.Max(1, tiles.x * tiles.y))), 2, 24);
                    float r = ts / perTile * 0.18f;
                    for (int z = 0; z < tiles.y; z++)
                        for (int x = 0; x < tiles.x; x++)
                        {
                            g.GetTileUVTransform(x, z, out int rot, out Vector2 ofs);
                            for (int j = 0; j < perTile; j++)
                                for (int i = 0; i < perTile; i++)
                                {
                                    var tl = new Vector2((i + 0.5f) / perTile, (j + 0.5f) / perTile);
                                    var local = min + new Vector2((x + tl.x) * ts, (z + tl.y) * ts);
                                    if (local.x > min.x + area.x || local.y > min.y + area.y) continue;
                                    Vector2 uv = g.densityMapMode == StylizedGrassRenderer.DensityMapMode.StretchAcrossArea
                                        ? new Vector2((local.x - min.x) / area.x, (local.y - min.y) / area.y)
                                        : StylizedGrassRenderer.TileLocalToUV(tl, rot, ofs);
                                    float v = DensityMapReader.SampleBilinear(s_Map, s_W, s_H, uv, g.densityMapMode == StylizedGrassRenderer.DensityMapMode.RepeatPerTile);
                                    Handles.color = new Color(v, v, v, 0.9f);
                                    Handles.DrawSolidDisc(L(local.x, local.y), Vector3.up, r);
                                }
                        }
                }
            }

            if (EditorPrefs.GetBool(StylizedGrassRendererEditor.k_PrefChunks, false) && g.Chunks != null)
            {
                Gizmos.color = new Color(1f, 0.85f, 0.2f, 0.5f);
                foreach (var ch in g.Chunks) Gizmos.DrawWireCube(ch.bounds.center, ch.bounds.size);
            }
        }

        static Vector3 L(float x, float z) => new Vector3(x, 0.02f, z);

        // Draws the density map's U/V axes as they land in this tile (inverse of TileLocalToUV).
        static void DrawUVAxes(Vector2 tileMin, Vector2 size, int rot, Vector2 ofs, bool label)
        {
            Vector2 Inv(Vector2 uv)
            {
                Vector2 p = uv - new Vector2(0.5f, 0.5f);
                switch (rot & 3)
                {
                    case 1: p = new Vector2(p.y, -p.x); break;
                    case 2: p = new Vector2(-p.x, -p.y); break;
                    case 3: p = new Vector2(-p.y, p.x); break;
                }
                return p + new Vector2(0.5f, 0.5f);
            }
            Vector3 W(Vector2 t) => L(tileMin.x + t.x * size.x, tileMin.y + t.y * size.y);

            Vector3 o = W(Inv(new Vector2(0.08f, 0.08f)));
            Vector3 u = W(Inv(new Vector2(0.38f, 0.08f)));
            Vector3 v = W(Inv(new Vector2(0.08f, 0.38f)));
            Handles.color = k_U; Handles.DrawAAPolyLine(4f, o, u); Arrow(o, u);
            Handles.color = k_V; Handles.DrawAAPolyLine(4f, o, v); Arrow(o, v);
            if (ofs != Vector2.zero)
            {
                // Where the map's (0,0) texel lands after the per-tile offset.
                Vector2 t0 = Inv(new Vector2(Frac(-ofs.x), Frac(-ofs.y)));
                Handles.color = Color.white;
                Handles.DrawWireDisc(W(t0), Vector3.up, Mathf.Min(size.x, size.y) * 0.03f);
            }
            if (label) Handles.Label(o, rot == 0 ? " UV (0,0)" : $" UV (0,0) rot {rot * 90}°");
        }

        static float Frac(float x) => x - Mathf.Floor(x);

        static void Arrow(Vector3 from, Vector3 to)
        {
            Vector3 dir = to - from; float len = dir.magnitude; if (len < 1e-4f) return;
            dir /= len;
            Vector3 side = Vector3.Cross(Vector3.up, dir) * len * 0.12f;
            Vector3 back = to - dir * len * 0.2f;
            Handles.DrawAAPolyLine(4f, back + side, to, back - side);
        }

        static bool EnsureMap(StylizedGrassRenderer g)
        {
            var hash = g.densityMap.imageContentsHash;
            if (s_Map != null && s_CachedTex == g.densityMap && s_CachedHash == hash && s_CachedChannel == g.densityChannel) return true;
            s_Map = null;
            if (!DensityMapReader.Read(g.densityMap, g.densityChannel, out s_Map, out s_W, out s_H, out _)) return false;
            s_CachedTex = g.densityMap; s_CachedHash = hash; s_CachedChannel = g.densityChannel;
            return true;
        }
    }

    static class StylizedGrassMenu
    {
        [MenuItem("GameObject/LJ Environment Tools/Stylized Grass", false, 10)]
        static void Create(MenuCommand cmd)
        {
            var go = new GameObject("Stylized Grass");
            GameObjectUtility.SetParentAndAlign(go, cmd.context as GameObject);
            if (SceneView.lastActiveSceneView != null && cmd.context == null)
                go.transform.position = SceneView.lastActiveSceneView.pivot;
            go.AddComponent<StylizedGrassRenderer>();
            Undo.RegisterCreatedObjectUndo(go, "Create Stylized Grass");
            Selection.activeGameObject = go;
        }
    }
}
