using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.Formats.Fbx.Exporter;
using UnityEngine;

namespace LJ.EditorTools
{
    public static class LJFbxExporter
    {
        //Set For BLENDER EXPORT
        public const string LogPrefix = "[LJ Environment Tools]";
        public const string DefaultExportFolder = "../exports";

        private const string VerboseLoggingPrefKey = "LJ.EnvTools.VerboseLogging";

        public static bool VerboseLogging
        {
            get => EditorPrefs.GetBool(VerboseLoggingPrefKey, false);
            set => EditorPrefs.SetBool(VerboseLoggingPrefKey, value);
        }

        public static void LogVerbose(string message)
        {
            if (VerboseLogging) Debug.Log(message);
        }

        private const ExportFormat Format = ExportFormat.Binary;
        private const Include IncludeOption = Include.Model;
        private const ObjectPosition Position = ObjectPosition.LocalCentered;
        private const LODExportType LODMode = LODExportType.All;
        private const bool ExportUnrendered = true;
        private const bool KeepInstances = false;
        private const bool EmbedTextures = false;
        private const bool AnimateSkinnedMesh = false;
        private const bool UseMayaCompatibleNames = false;
        private const bool PreserveImportSettings = false;

        public static string ExportSelection()
        {
            GameObject[] selection = Selection.gameObjects;
            if (selection == null || selection.Length == 0)
            {
                EditorUtility.DisplayDialog("Export to FBX", "Select one or more GameObjects first.", "OK");
                return null;
            }

            GameObject topmost = GetTopmostInHierarchy(selection);
            string suggestedName = SanitizeFileName(topmost.name) + ".fbx";

            string absFolder = Path.GetFullPath(DefaultExportFolder);
            if (!Directory.Exists(absFolder))
            {
                Directory.CreateDirectory(absFolder);
            }

            string filePath = GetUniquePath(Path.Combine(absFolder, suggestedName));

            ExportModelOptions options = new ExportModelOptions
            {
                ExportFormat = Format,
                ModelAnimIncludeOption = IncludeOption,
                ObjectPosition = Position,
                LODExportType = LODMode,
                ExportUnrendered = ExportUnrendered,
                KeepInstances = KeepInstances,
                EmbedTextures = EmbedTextures,
                AnimateSkinnedMesh = AnimateSkinnedMesh,
                UseMayaCompatibleNames = UseMayaCompatibleNames,
                PreserveImportSettings = PreserveImportSettings,
            };

            string result = ModelExporter.ExportObjects(filePath, selection, options);

            if (!string.IsNullOrEmpty(result))
            {
                Debug.Log($"{LogPrefix} Exported {selection.Length} object(s) to: {result}");
                if (result.StartsWith(Application.dataPath))
                {
                    AssetDatabase.Refresh();
                    string projectRelative = "Assets" + result.Substring(Application.dataPath.Length);
                    Object asset = AssetDatabase.LoadAssetAtPath<Object>(projectRelative);
                    if (asset != null)
                    {
                        EditorGUIUtility.PingObject(asset);
                    }
                }
                return result;
            }

            Debug.LogError($"{LogPrefix} FBX export failed.");
            return null;
        }

        private static GameObject GetTopmostInHierarchy(GameObject[] objects)
        {
            GameObject best = objects[0];
            List<int> bestPath = GetHierarchyPath(best.transform);
            for (int i = 1; i < objects.Length; i++)
            {
                List<int> path = GetHierarchyPath(objects[i].transform);
                if (ComparePaths(path, bestPath) < 0)
                {
                    best = objects[i];
                    bestPath = path;
                }
            }
            return best;
        }

        private static List<int> GetHierarchyPath(Transform t)
        {
            List<int> indices = new List<int>();
            while (t != null)
            {
                indices.Add(t.GetSiblingIndex());
                t = t.parent;
            }
            indices.Reverse();
            return indices;
        }

        private static int ComparePaths(List<int> a, List<int> b)
        {
            int len = a.Count < b.Count ? a.Count : b.Count;
            for (int i = 0; i < len; i++)
            {
                if (a[i] != b[i])
                {
                    return a[i] < b[i] ? -1 : 1;
                }
            }
            return a.Count.CompareTo(b.Count);
        }

        private static string SanitizeFileName(string name)
        {
            foreach (char c in Path.GetInvalidFileNameChars())
            {
                name = name.Replace(c, '_');
            }
            return name;
        }

        private static string GetUniquePath(string path)
        {
            if (!File.Exists(path))
            {
                return path;
            }

            string dir = Path.GetDirectoryName(path);
            string stem = Path.GetFileNameWithoutExtension(path);
            string ext = Path.GetExtension(path);
            int i = 1;
            string candidate;
            do
            {
                candidate = Path.Combine(dir, $"{stem}_{i:000}{ext}");
                i++;
            }
            while (File.Exists(candidate));
            return candidate;
        }
    }
}
