using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace LJ.EditorTools
{
    public static class LJAutoMaterialCreator
    {
        public enum ShaderType
        {
            BetterLit = 0,
            HDRPLit = 1,
            URPLit = 2,
        }

        private const string EnabledPrefKey = "LJ.AutoMaterial.Enabled";
        private const string RootPathPrefKey = "LJ.AutoMaterial.RootPath";
        private const string OutputPathPrefKey = "LJ.AutoMaterial.OutputPath";
        private const string ShaderTypePrefKey = "LJ.AutoMaterial.ShaderType";
        private const string SnapshotPrefKey = "LJ.AutoMaterial.Snapshot";
        private const string SectionExpandedPrefKey = "LJ.AutoMaterial.SectionExpanded";
        private const char SnapshotSeparator = '|';

        private const string AlbedoKeyword = "Albedo";
        private const string MaskMapKeyword = "Mask_Map";
        private const string NormalKeyword = "Normal";
        private const string MetallicSmoothnessKeyword = "MetallicSmoothness";
        private const string OcclusionKeyword = "Occlusion";

        private class TextureSlot
        {
            public string Keyword;
            public string[] ExcludeKeywords;
            public string Property;
            public bool ForceLinear;
            public bool ForceNormalMap;
            public bool Required;
        }

        private class ShaderConfig
        {
            public string ShaderName;
            public TextureSlot[] Slots;
        }

        private static readonly Dictionary<ShaderType, ShaderConfig> _configs = new Dictionary<ShaderType, ShaderConfig>
        {
            [ShaderType.BetterLit] = new ShaderConfig
            {
                ShaderName = "Better Lit/Lit",
                Slots = new[]
                {
                    new TextureSlot { Keyword = AlbedoKeyword, Property = "_AlbedoMap", Required = true },
                    new TextureSlot { Keyword = MaskMapKeyword, Property = "_MaskMap", ForceLinear = true, Required = true },
                    new TextureSlot { Keyword = NormalKeyword, ExcludeKeywords = new[] { MaskMapKeyword }, Property = "_NormalMap", ForceNormalMap = true, Required = true },
                },
            },
            [ShaderType.HDRPLit] = new ShaderConfig
            {
                ShaderName = "HDRP/Lit",
                Slots = new[]
                {
                    new TextureSlot { Keyword = AlbedoKeyword, Property = "_BaseColorMap", Required = true },
                    new TextureSlot { Keyword = MaskMapKeyword, Property = "_MaskMap", ForceLinear = true, Required = true },
                    new TextureSlot { Keyword = NormalKeyword, ExcludeKeywords = new[] { MaskMapKeyword }, Property = "_NormalMap", ForceNormalMap = true, Required = true },
                },
            },
            [ShaderType.URPLit] = new ShaderConfig
            {
                ShaderName = "Universal Render Pipeline/Lit",
                Slots = new[]
                {
                    new TextureSlot { Keyword = AlbedoKeyword, Property = "_BaseMap", Required = true },
                    new TextureSlot { Keyword = MetallicSmoothnessKeyword, Property = "_MetallicGlossMap", ForceLinear = true, Required = true },
                    new TextureSlot { Keyword = NormalKeyword, ExcludeKeywords = new[] { MaskMapKeyword, MetallicSmoothnessKeyword }, Property = "_BumpMap", ForceNormalMap = true, Required = true },
                    new TextureSlot { Keyword = OcclusionKeyword, Property = "_OcclusionMap", ForceLinear = true, Required = false },
                },
            },
        };

        private static bool _initialized;
        private static bool _enabled;
        private static string _rootPath;
        private static string _outputPath;
        private static ShaderType _shaderType;
        private static HashSet<string> _snapshot;
        private static bool _sectionExpanded = true;

        public static bool Enabled
        {
            get { EnsureInitialized(); return _enabled; }
        }

        [InitializeOnLoadMethod]
        private static void OnEditorLoad()
        {
            EditorApplication.delayCall += () =>
            {
                EnsureInitialized();
                TakeSnapshot();
            };
        }

        public static void DrawGUI()
        {
            EnsureInitialized();

            EditorGUI.BeginChangeCheck();
            _sectionExpanded = EditorGUILayout.Foldout(_sectionExpanded, "Auto Material Creator 🎨", true, EditorStyles.foldoutHeader);
            if (EditorGUI.EndChangeCheck())
            {
                EditorPrefs.SetBool(SectionExpandedPrefKey, _sectionExpanded);
            }
            if (!_sectionExpanded)
                return;

            GUILayout.Space(LJEnvironmentTools.FoldoutPadding);

            DrawFolderField("Root Path", ref _rootPath, RootPathPrefKey, "Select root material folder (inside Assets/)");
            DrawFolderField("Output Path", ref _outputPath, OutputPathPrefKey, "Select material output folder (inside Assets/) — leave empty to write next to the textures");

            EditorGUI.BeginChangeCheck();
            ShaderType newShader = (ShaderType)EditorGUILayout.EnumPopup("Shader", _shaderType);
            if (EditorGUI.EndChangeCheck())
            {
                _shaderType = newShader;
                EditorPrefs.SetInt(ShaderTypePrefKey, (int)_shaderType);
            }

            using (new EditorGUI.DisabledScope(!HasTextureInProjectSelection()))
            {
                if (GUILayout.Button("Create Material From Selection", GUILayout.Height(24)))
                {
                    CreateMaterialForSelection();
                }
            }

            EditorGUI.BeginChangeCheck();
            bool newEnabled = EditorGUILayout.Toggle("Enabled", _enabled);
            if (EditorGUI.EndChangeCheck())
            {
                SetEnabled(newEnabled);
            }

            if (_enabled)
            {
                EditorGUILayout.LabelField($"Watching — snapshot of {_snapshot.Count} existing material folder(s).", EditorStyles.miniLabel);
                using (new EditorGUILayout.HorizontalScope())
                {
                    if (GUILayout.Button("Refresh Snapshot", GUILayout.Height(20)))
                    {
                        TakeSnapshot();
                    }
                    if (GUILayout.Button("Scan Now", GUILayout.Height(20)))
                    {
                        ScanAndCreate();
                    }
                }
            }
            else
            {
                ShaderConfig hint = _configs[_shaderType];
                EditorGUILayout.HelpBox(
                    "Enable to watch the Root Path. When a subfolder contains textures named " +
                    JoinKeywords(hint) + ", a material is created in that subfolder using the selected shader.",
                    MessageType.Info);
            }

            GUILayout.Space(LJEnvironmentTools.FoldoutPadding);
        }

        public static void OnAssetsRemoved(string[] deletedAssets, string[] movedFromAssetPaths)
        {
            EnsureInitialized();
            if (!_enabled) return;

            string root = NormalizeAssetsPath(_rootPath);
            if (string.IsNullOrEmpty(root)) return;
            string prefix = root + "/";

            if (PathsTouchRoot(deletedAssets, prefix) || PathsTouchRoot(movedFromAssetPaths, prefix))
            {
                TakeSnapshot();
            }
        }

        private static bool PathsTouchRoot(string[] paths, string prefix)
        {
            if (paths == null) return false;
            foreach (string assetPath in paths)
            {
                if (string.IsNullOrEmpty(assetPath)) continue;
                string normalized = assetPath.Replace('\\', '/');
                if (normalized.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
            return false;
        }

        public static void OnAssetsImported(string[] importedAssets)
        {
            EnsureInitialized();
            if (!_enabled || importedAssets == null || importedAssets.Length == 0)
            {
                return;
            }

            string root = NormalizeAssetsPath(_rootPath);
            if (string.IsNullOrEmpty(root))
            {
                return;
            }

            HashSet<string> subfoldersToCheck = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string assetPath in importedAssets)
            {
                if (string.IsNullOrEmpty(assetPath)) continue;
                if (!IsTextureAsset(assetPath)) continue;

                string normalized = assetPath.Replace('\\', '/');
                if (!normalized.StartsWith(root + "/", StringComparison.OrdinalIgnoreCase)) continue;

                string subfolder = GetSubfolderUnderRoot(normalized, root);
                if (string.IsNullOrEmpty(subfolder)) continue;
                if (_snapshot.Contains(subfolder)) continue;
                subfoldersToCheck.Add(subfolder);
            }

            bool snapshotChanged = false;
            foreach (string subfolder in subfoldersToCheck)
            {
                if (TryCreateMaterial(subfolder))
                {
                    _snapshot.Add(subfolder);
                    snapshotChanged = true;
                }
            }

            if (snapshotChanged)
            {
                SaveSnapshot();
            }
        }

        private static void ScanAndCreate()
        {
            string root = NormalizeAssetsPath(_rootPath);
            if (string.IsNullOrEmpty(root) || !AssetDatabase.IsValidFolder(root))
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Material — root path is not a valid Assets folder: {_rootPath}");
                return;
            }

            string[] subFolders = AssetDatabase.GetSubFolders(root);
            bool snapshotChanged = false;
            foreach (string raw in subFolders)
            {
                string subfolder = raw.Replace('\\', '/');
                if (_snapshot.Contains(subfolder)) continue;
                if (TryCreateMaterial(subfolder))
                {
                    _snapshot.Add(subfolder);
                    snapshotChanged = true;
                }
            }

            if (snapshotChanged)
            {
                SaveSnapshot();
            }
        }

        private static bool TryCreateMaterial(string subfolder, bool requireAll = true)
        {
            if (!AssetDatabase.IsValidFolder(subfolder)) return false;

            ShaderConfig config = _configs[_shaderType];

            string folderName = Path.GetFileName(subfolder);
            string materialPath = GetMaterialPath(subfolder, folderName);
            if (materialPath == null) return false;

            if (AssetDatabase.LoadAssetAtPath<Material>(materialPath) != null)
            {
                if (!requireAll)
                {
                    LJFbxExporter.LogVerbose($"{LJFbxExporter.LogPrefix} Auto Material — {materialPath} already exists, skipping.");
                }
                return true;
            }

            var found = new Dictionary<TextureSlot, Texture2D>();
            foreach (TextureSlot slot in config.Slots)
            {
                Texture2D tex = FindTextureByKeyword(subfolder, slot.Keyword, slot.ExcludeKeywords);
                if (tex != null) found[slot] = tex;
            }

            if (requireAll)
            {
                foreach (TextureSlot slot in config.Slots)
                {
                    if (slot.Required && !found.ContainsKey(slot)) return false;
                }
            }
            else if (found.Count == 0)
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Material — no supported textures ({JoinKeywords(config)}) found in {subfolder}.");
                return false;
            }

            Shader shader = Shader.Find(config.ShaderName);
            if (shader == null)
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Material — shader '{config.ShaderName}' not found.");
                return false;
            }
            Material material = new Material(shader);

            foreach (var kvp in found)
            {
                TextureSlot slot = kvp.Key;
                Texture2D tex = kvp.Value;
                if (slot.ForceNormalMap) EnsureNormalMapImport(tex);
                else if (slot.ForceLinear) EnsureLinearImport(tex);
                SetTextureIfPresent(material, slot.Property, tex);
            }

            AssetDatabase.CreateAsset(material, materialPath);
            Debug.Log($"{LJFbxExporter.LogPrefix} Auto Material — created {materialPath} ({_shaderType})");
            return true;
        }

        private static string JoinKeywords(ShaderConfig config)
        {
            string[] kws = new string[config.Slots.Length];
            for (int i = 0; i < config.Slots.Length; i++) kws[i] = config.Slots[i].Keyword;
            return string.Join(", ", kws);
        }

        private static void CreateMaterialForSelection()
        {
            EnsureInitialized();

            HashSet<string> folders = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (UnityEngine.Object obj in Selection.objects)
            {
                if (obj == null) continue;
                string path = AssetDatabase.GetAssetPath(obj);
                if (string.IsNullOrEmpty(path)) continue;
                path = path.Replace('\\', '/');
                if (!IsTextureAsset(path)) continue;
                if (!IsSupportedTextureName(Path.GetFileNameWithoutExtension(path))) continue;

                string parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
                if (string.IsNullOrEmpty(parent)) continue;
                folders.Add(parent);
            }

            if (folders.Count == 0)
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Material — select at least one texture named {JoinKeywords(_configs[_shaderType])} in the Project window.");
                return;
            }

            bool snapshotChanged = false;
            foreach (string folder in folders)
            {
                if (TryCreateMaterial(folder, requireAll: false))
                {
                    if (_snapshot.Add(folder)) snapshotChanged = true;
                }
            }
            if (snapshotChanged) SaveSnapshot();
        }

        private static bool HasTextureInProjectSelection()
        {
            string[] guids = Selection.assetGUIDs;
            if (guids == null || guids.Length == 0) return false;
            foreach (string guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                if (!string.IsNullOrEmpty(path) && IsTextureAsset(path)) return true;
            }
            return false;
        }

        private static string GetMaterialPath(string subfolder, string folderName)
        {
            string output = NormalizeAssetsPath(_outputPath);
            if (string.IsNullOrEmpty(output))
            {
                return subfolder + "/" + folderName + ".mat";
            }
            if (!AssetDatabase.IsValidFolder(output))
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Material — output path is not a valid Assets folder: {_outputPath}");
                return null;
            }
            return output + "/" + folderName + ".mat";
        }

        private static bool IsSupportedTextureName(string fileName)
        {
            if (string.IsNullOrEmpty(fileName)) return false;
            ShaderConfig config = _configs[_shaderType];
            foreach (TextureSlot slot in config.Slots)
            {
                if (fileName.IndexOf(slot.Keyword, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            }
            return false;
        }

        private static void SetTextureIfPresent(Material material, string property, Texture2D texture)
        {
            if (material.HasProperty(property))
            {
                material.SetTexture(property, texture);
            }
            else
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Material — shader '{material.shader.name}' has no property '{property}'.");
            }
        }

        private static void EnsureNormalMapImport(Texture2D normal)
        {
            if (normal == null) return;
            string path = AssetDatabase.GetAssetPath(normal);
            if (string.IsNullOrEmpty(path)) return;

            TextureImporter importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) return;
            if (importer.textureType == TextureImporterType.NormalMap) return;

            importer.textureType = TextureImporterType.NormalMap;
            importer.SaveAndReimport();
        }

        private static void EnsureLinearImport(Texture2D texture)
        {
            if (texture == null) return;
            string path = AssetDatabase.GetAssetPath(texture);
            if (string.IsNullOrEmpty(path)) return;

            TextureImporter importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) return;
            if (!importer.sRGBTexture) return;

            importer.sRGBTexture = false;
            importer.SaveAndReimport();
        }

        private static Texture2D FindTextureByKeyword(string folder, string keyword, params string[] excludeKeywords)
        {
            string[] guids = AssetDatabase.FindAssets("t:Texture2D", new[] { folder });
            foreach (string guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid).Replace('\\', '/');

                string parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
                if (!string.Equals(parent, folder, StringComparison.OrdinalIgnoreCase)) continue;

                string fileName = Path.GetFileNameWithoutExtension(path);
                if (fileName.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) < 0) continue;

                bool excluded = false;
                if (excludeKeywords != null)
                {
                    foreach (string ex in excludeKeywords)
                    {
                        if (!string.IsNullOrEmpty(ex) && fileName.IndexOf(ex, StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            excluded = true;
                            break;
                        }
                    }
                }
                if (excluded) continue;

                Texture2D tex = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
                if (tex != null) return tex;
            }
            return null;
        }

        private static bool IsTextureAsset(string assetPath)
        {
            string ext = Path.GetExtension(assetPath);
            if (string.IsNullOrEmpty(ext)) return false;
            switch (ext.ToLowerInvariant())
            {
                case ".png":
                case ".tga":
                case ".jpg":
                case ".jpeg":
                case ".tif":
                case ".tiff":
                case ".psd":
                case ".bmp":
                case ".exr":
                case ".hdr":
                    return true;
                default:
                    return false;
            }
        }

        private static string GetSubfolderUnderRoot(string assetPath, string root)
        {
            string prefix = root + "/";
            if (!assetPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return null;
            string remainder = assetPath.Substring(prefix.Length);
            int slash = remainder.IndexOf('/');
            if (slash <= 0) return null;
            return root + "/" + remainder.Substring(0, slash);
        }

        private static void DrawFolderField(string label, ref string value, string prefKey, string panelTitle)
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUI.BeginChangeCheck();
                string newValue = EditorGUILayout.TextField(label, value);
                if (EditorGUI.EndChangeCheck())
                {
                    value = newValue;
                    EditorPrefs.SetString(prefKey, value ?? string.Empty);
                }

                if (GUILayout.Button("Browse...", GUILayout.Width(80)))
                {
                    string start = !string.IsNullOrEmpty(value) && Directory.Exists(value)
                        ? Path.GetFullPath(value)
                        : Application.dataPath;
                    string picked = EditorUtility.OpenFolderPanel(panelTitle, start, string.Empty);
                    if (!string.IsNullOrEmpty(picked))
                    {
                        string rel = ToAssetsRelative(picked);
                        if (string.IsNullOrEmpty(rel))
                        {
                            Debug.LogWarning($"{LJFbxExporter.LogPrefix} Folder must be inside the project's Assets/ directory.");
                        }
                        else
                        {
                            value = rel;
                            EditorPrefs.SetString(prefKey, value);
                        }
                    }
                }
            }
        }

        private static void SetEnabled(bool enabled)
        {
            _enabled = enabled;
            EditorPrefs.SetBool(EnabledPrefKey, _enabled);
            if (_enabled)
            {
                TakeSnapshot();
            }
        }

        private static void TakeSnapshot()
        {
            _snapshot = new HashSet<string>();
            string root = NormalizeAssetsPath(_rootPath);
            if (string.IsNullOrEmpty(root) || !AssetDatabase.IsValidFolder(root))
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Material — root path is not a valid Assets folder: {_rootPath}");
                SaveSnapshot();
                return;
            }

            string[] subFolders = AssetDatabase.GetSubFolders(root);
            foreach (string raw in subFolders)
            {
                string subfolder = raw.Replace('\\', '/');
                string folderName = Path.GetFileName(subfolder);
                string materialPath = GetMaterialPath(subfolder, folderName);
                if (materialPath == null) continue;
                if (AssetDatabase.LoadAssetAtPath<Material>(materialPath) != null)
                {
                    _snapshot.Add(subfolder);
                }
            }
            SaveSnapshot();
            LJFbxExporter.LogVerbose($"{LJFbxExporter.LogPrefix} Auto Material — snapshot captured {_snapshot.Count} subfolder(s) with materials in {root}");
        }

        private static void EnsureInitialized()
        {
            if (_initialized) return;
            _enabled = EditorPrefs.GetBool(EnabledPrefKey, false);
            _rootPath = EditorPrefs.GetString(RootPathPrefKey, string.Empty);
            _outputPath = EditorPrefs.GetString(OutputPathPrefKey, string.Empty);
            _shaderType = (ShaderType)EditorPrefs.GetInt(ShaderTypePrefKey, (int)ShaderType.BetterLit);
            _sectionExpanded = EditorPrefs.GetBool(SectionExpandedPrefKey, true);

            _snapshot = new HashSet<string>();
            string raw = EditorPrefs.GetString(SnapshotPrefKey, string.Empty);
            if (!string.IsNullOrEmpty(raw))
            {
                foreach (string entry in raw.Split(SnapshotSeparator))
                {
                    if (!string.IsNullOrEmpty(entry))
                    {
                        _snapshot.Add(entry);
                    }
                }
            }
            _initialized = true;
        }

        private static void SaveSnapshot()
        {
            EditorPrefs.SetString(SnapshotPrefKey, string.Join(SnapshotSeparator.ToString(), _snapshot));
        }

        private static string NormalizeAssetsPath(string path)
        {
            if (string.IsNullOrEmpty(path)) return null;
            string normalized = path.Replace('\\', '/').TrimEnd('/');
            if (!normalized.StartsWith("Assets", StringComparison.OrdinalIgnoreCase)) return null;
            return normalized;
        }

        private static string ToAssetsRelative(string absolutePath)
        {
            string normalizedAbs = Path.GetFullPath(absolutePath).Replace('\\', '/').TrimEnd('/');
            string dataPath = Application.dataPath.Replace('\\', '/').TrimEnd('/');
            if (string.Equals(normalizedAbs, dataPath, StringComparison.OrdinalIgnoreCase))
            {
                return "Assets";
            }
            string prefix = dataPath + "/";
            if (normalizedAbs.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                return "Assets/" + normalizedAbs.Substring(prefix.Length);
            }
            return null;
        }
    }

    public class LJAutoMaterialImportWatcher : AssetPostprocessor
    {
        private static void OnPostprocessAllAssets(string[] importedAssets, string[] deletedAssets, string[] movedAssets, string[] movedFromAssetPaths)
        {
            if (!LJAutoMaterialCreator.Enabled) return;
            LJAutoMaterialCreator.OnAssetsRemoved(deletedAssets, movedFromAssetPaths);
            LJAutoMaterialCreator.OnAssetsImported(importedAssets);
            LJAutoMaterialCreator.OnAssetsImported(movedAssets);
        }
    }
}
