using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace LJ.EditorTools
{
    public static class LJAutoPrefabCreator
    {
        private const string EnabledPrefKey = "LJ.AutoPrefab.Enabled";
        private const string ExportPathPrefKey = "LJ.AutoPrefab.ExportPath";
        private const string PrefabPathPrefKey = "LJ.AutoPrefab.PrefabPath";
        private const string SnapshotPrefKey = "LJ.AutoPrefab.Snapshot";
        private const string OptionsExpandedPrefKey = "LJ.AutoPrefab.OptionsExpanded";
        private const string OptionStaticMeshPrefKey = "LJ.AutoPrefab.Option.StaticMesh";
        private const string SectionExpandedPrefKey = "LJ.AutoPrefab.SectionExpanded";
        private const char SnapshotSeparator = '|';

        private static bool _initialized;
        private static bool _enabled;
        private static string _exportPath;
        private static string _prefabPath;
        private static HashSet<string> _snapshot;
        private static bool _optionsExpanded;
        private static bool _optionStaticMesh;
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
                if (_enabled)
                {
                    TakeSnapshot();
                }
            };
        }

        public static void DrawGUI()
        {
            EnsureInitialized();

            EditorGUI.BeginChangeCheck();
            _sectionExpanded = EditorGUILayout.Foldout(_sectionExpanded, "Auto Prefab Creator ✨", true, EditorStyles.foldoutHeader);
            if (EditorGUI.EndChangeCheck())
            {
                EditorPrefs.SetBool(SectionExpandedPrefKey, _sectionExpanded);
            }
            if (!_sectionExpanded)
                return;

            GUILayout.Space(LJEnvironmentTools.FoldoutPadding);

            DrawFolderField("Export Path", ref _exportPath, ExportPathPrefKey, "Select FBX export folder (inside Assets/)");
            DrawFolderField("Prefab Path", ref _prefabPath, PrefabPathPrefKey, "Select prefab output folder (inside Assets/)");

            DrawOptions();

            EditorGUI.BeginChangeCheck();
            bool newEnabled = EditorGUILayout.Toggle("Enabled", _enabled);
            if (EditorGUI.EndChangeCheck())
            {
                SetEnabled(newEnabled);
            }

            if (_enabled)
            {
                EditorGUILayout.LabelField($"Watching — snapshot of {_snapshot.Count} existing fbx file(s).", EditorStyles.miniLabel);
                if (GUILayout.Button("Refresh Snapshot", GUILayout.Height(20)))
                {
                    TakeSnapshot();
                }
            }
            else
            {
                EditorGUILayout.HelpBox("Enable to snapshot existing fbx files in Export Path. New fbx files imported into that folder will become prefabs in Prefab Path.", MessageType.Info);
            }

            GUILayout.Space(LJEnvironmentTools.FoldoutPadding);
        }

        public static void OnFbxImported(string[] importedAssets)
        {
            EnsureInitialized();
            if (!_enabled || importedAssets == null || importedAssets.Length == 0)
            {
                return;
            }

            string exportRoot = NormalizeAssetsPath(_exportPath);
            string prefabRoot = NormalizeAssetsPath(_prefabPath);
            if (string.IsNullOrEmpty(exportRoot) || string.IsNullOrEmpty(prefabRoot))
            {
                return;
            }

            bool snapshotChanged = false;
            foreach (string assetPath in importedAssets)
            {
                if (string.IsNullOrEmpty(assetPath)) continue;
                if (!assetPath.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase)) continue;

                string normalized = assetPath.Replace('\\', '/');
                if (!normalized.StartsWith(exportRoot + "/", StringComparison.OrdinalIgnoreCase)) continue;
                if (_snapshot.Contains(normalized)) continue;

                if (TryCreatePrefab(normalized, prefabRoot))
                {
                    _snapshot.Add(normalized);
                    snapshotChanged = true;
                }
            }

            if (snapshotChanged)
            {
                SaveSnapshot();
            }
        }

        public static void OnFbxRemoved(string[] removedAssets)
        {
            EnsureInitialized();
            if (!_enabled || removedAssets == null || removedAssets.Length == 0)
            {
                return;
            }

            string exportRoot = NormalizeAssetsPath(_exportPath);
            if (string.IsNullOrEmpty(exportRoot))
            {
                return;
            }

            bool snapshotChanged = false;
            foreach (string assetPath in removedAssets)
            {
                if (string.IsNullOrEmpty(assetPath)) continue;
                if (!assetPath.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase)) continue;

                string normalized = assetPath.Replace('\\', '/');
                if (!normalized.StartsWith(exportRoot + "/", StringComparison.OrdinalIgnoreCase)) continue;

                if (_snapshot.Remove(normalized))
                {
                    snapshotChanged = true;
                    Debug.Log($"{LJFbxExporter.LogPrefix} Auto Prefab — snapshot dropped {normalized}");
                }
            }

            if (snapshotChanged)
            {
                SaveSnapshot();
            }
        }

        private static void DrawOptions()
        {
            EditorGUI.BeginChangeCheck();
            bool expanded = EditorGUILayout.Foldout(_optionsExpanded, "Options", true);
            if (EditorGUI.EndChangeCheck())
            {
                _optionsExpanded = expanded;
                EditorPrefs.SetBool(OptionsExpandedPrefKey, _optionsExpanded);
            }

            if (!_optionsExpanded) return;

            EditorGUI.indentLevel++;
            EditorGUI.BeginChangeCheck();
            bool staticMesh = EditorGUILayout.Toggle(new GUIContent("Static Mesh", "Mark the prefab root and all children as Static."), _optionStaticMesh);
            if (EditorGUI.EndChangeCheck())
            {
                _optionStaticMesh = staticMesh;
                EditorPrefs.SetBool(OptionStaticMeshPrefKey, _optionStaticMesh);
            }
            EditorGUI.indentLevel--;
        }

        private static void ApplyOptions(GameObject root)
        {
            if (_optionStaticMesh)
            {
                SetStaticRecursive(root, true);
            }
        }

        private static void SetStaticRecursive(GameObject go, bool isStatic)
        {
            go.isStatic = isStatic;
            foreach (Transform child in go.transform)
            {
                SetStaticRecursive(child.gameObject, isStatic);
            }
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
            string exportRoot = NormalizeAssetsPath(_exportPath);
            if (string.IsNullOrEmpty(exportRoot) || !AssetDatabase.IsValidFolder(exportRoot))
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Prefab — export path is not a valid Assets folder: {_exportPath}");
                SaveSnapshot();
                return;
            }

            string[] guids = AssetDatabase.FindAssets("t:Model", new[] { exportRoot });
            foreach (string guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                if (path.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase))
                {
                    _snapshot.Add(path.Replace('\\', '/'));
                }
            }
            SaveSnapshot();
            Debug.Log($"{LJFbxExporter.LogPrefix} Auto Prefab — snapshot captured {_snapshot.Count} fbx file(s) in {exportRoot}");
        }

        private static bool TryCreatePrefab(string fbxAssetPath, string prefabRoot)
        {
            if (!AssetDatabase.IsValidFolder(prefabRoot))
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Prefab — prefab path is not a valid Assets folder: {prefabRoot}");
                return false;
            }

            GameObject fbx = AssetDatabase.LoadAssetAtPath<GameObject>(fbxAssetPath);
            if (fbx == null)
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Prefab — could not load fbx at {fbxAssetPath}");
                return false;
            }

            string fileName = Path.GetFileNameWithoutExtension(fbxAssetPath) + ".prefab";
            string targetPath = AssetDatabase.GenerateUniqueAssetPath(prefabRoot + "/" + fileName);

            GameObject instance = (GameObject)PrefabUtility.InstantiatePrefab(fbx);
            if (instance == null)
            {
                Debug.LogWarning($"{LJFbxExporter.LogPrefix} Auto Prefab — failed to instantiate {fbxAssetPath}");
                return false;
            }

            try
            {
                PrefabUtility.UnpackPrefabInstance(instance, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
                ApplyOptions(instance);
                PrefabUtility.SaveAsPrefabAsset(instance, targetPath);
                Debug.Log($"{LJFbxExporter.LogPrefix} Auto Prefab — created {targetPath} from {fbxAssetPath}");
                return true;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(instance);
            }
        }

        private static void EnsureInitialized()
        {
            if (_initialized) return;
            _enabled = EditorPrefs.GetBool(EnabledPrefKey, false);
            _exportPath = EditorPrefs.GetString(ExportPathPrefKey, string.Empty);
            _prefabPath = EditorPrefs.GetString(PrefabPathPrefKey, string.Empty);
            _optionsExpanded = EditorPrefs.GetBool(OptionsExpandedPrefKey, false);
            _optionStaticMesh = EditorPrefs.GetBool(OptionStaticMeshPrefKey, false);
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

    public class LJAutoPrefabImportWatcher : AssetPostprocessor
    {
        private static void OnPostprocessAllAssets(string[] importedAssets, string[] deletedAssets, string[] movedAssets, string[] movedFromAssetPaths)
        {
            if (!LJAutoPrefabCreator.Enabled) return;
            LJAutoPrefabCreator.OnFbxImported(importedAssets);
            LJAutoPrefabCreator.OnFbxRemoved(deletedAssets);
            LJAutoPrefabCreator.OnFbxRemoved(movedFromAssetPaths);
        }
    }
}
