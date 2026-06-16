using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace LJ.EditorTools
{
    public static class LJBlenderFileBrowser
    {
        private const string SearchPathPrefKey = "LJ.BlenderBrowser.SearchPath";
        private const int ButtonsPerRow = 4;
        private const float ButtonHeight = 28f;
        private const float RowSpacing = 2f;
        private const int VisibleRows = 3;
        private const float MaxListHeight = (ButtonHeight + RowSpacing) * VisibleRows + RowSpacing;

        private static string _searchPath;
        private static List<string> _indexedFiles;
        private static Vector2 _scroll;
        private static bool _initialized;

        public static void DrawGUI()
        {
            EnsureInitialized();

            GUILayout.Label("Blender File Browser 🏝️", EditorStyles.boldLabel);

            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUI.BeginChangeCheck();
                string newPath = EditorGUILayout.TextField("Search Path", _searchPath);
                if (EditorGUI.EndChangeCheck())
                {
                    _searchPath = newPath;
                    EditorPrefs.SetString(SearchPathPrefKey, _searchPath ?? string.Empty);
                }

                if (GUILayout.Button("Browse...", GUILayout.Width(80)))
                {
                    string start = !string.IsNullOrEmpty(_searchPath) && Directory.Exists(_searchPath)
                        ? _searchPath
                        : Application.dataPath;
                    string picked = EditorUtility.OpenFolderPanel("Select folder to index", start, string.Empty);
                    if (!string.IsNullOrEmpty(picked))
                    {
                        _searchPath = picked;
                        EditorPrefs.SetString(SearchPathPrefKey, _searchPath);
                        IndexFiles();
                    }
                }
            }

            using (new EditorGUI.DisabledScope(string.IsNullOrEmpty(_searchPath) || !Directory.Exists(_searchPath)))
            {
                if (GUILayout.Button("Index Blender Files", GUILayout.Height(24)))
                {
                    IndexFiles();
                }
            }

            if (_indexedFiles == null || _indexedFiles.Count == 0)
            {
                EditorGUILayout.HelpBox("No .blend files indexed yet. Pick a folder and press Index.", MessageType.Info);
                return;
            }

            EditorGUILayout.LabelField($"Found {_indexedFiles.Count} .blend file(s)", EditorStyles.miniLabel);

            int rowCount = Mathf.CeilToInt(_indexedFiles.Count / (float)ButtonsPerRow);
            float contentHeight = (ButtonHeight + RowSpacing) * Mathf.Min(rowCount, VisibleRows) + RowSpacing;
            _scroll = EditorGUILayout.BeginScrollView(_scroll, GUILayout.Height(contentHeight));
            for (int i = 0; i < _indexedFiles.Count; i += ButtonsPerRow)
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    for (int j = 0; j < ButtonsPerRow; j++)
                    {
                        int index = i + j;
                        if (index >= _indexedFiles.Count)
                        {
                            GUILayout.FlexibleSpace();
                            continue;
                        }

                        string file = _indexedFiles[index];
                        string label = Path.GetFileNameWithoutExtension(file);
                        if (GUILayout.Button(new GUIContent(label, file), GUILayout.Height(ButtonHeight), GUILayout.ExpandWidth(true)))
                        {
                            LJBlenderLauncher.LaunchBlendFile(file);
                        }
                    }
                }
            }
            EditorGUILayout.EndScrollView();
        }

        private static void EnsureInitialized()
        {
            if (_initialized)
            {
                return;
            }
            _searchPath = EditorPrefs.GetString(SearchPathPrefKey, string.Empty);
            _initialized = true;
        }

        [InitializeOnLoadMethod]
        private static void AutoIndexOnEditorLoad()
        {
            EnsureInitialized();
            if (!string.IsNullOrEmpty(_searchPath) && Directory.Exists(_searchPath))
            {
                IndexFiles();
            }
        }

        private static void IndexFiles()
        {
            _indexedFiles = new List<string>();

            if (string.IsNullOrEmpty(_searchPath) || !Directory.Exists(_searchPath))
            {
                Debug.LogWarning($"{LJBlenderLauncher.LogPrefix} Search path is invalid: {_searchPath}");
                return;
            }

            try
            {
                string[] found = Directory.GetFiles(_searchPath, "*.blend", SearchOption.AllDirectories);
                foreach (string file in found)
                {
                    string ext = Path.GetExtension(file);
                    if (string.Equals(ext, ".blend", StringComparison.OrdinalIgnoreCase))
                    {
                        _indexedFiles.Add(file);
                    }
                }
                _indexedFiles.Sort(StringComparer.OrdinalIgnoreCase);
                Debug.Log($"{LJBlenderLauncher.LogPrefix} Indexed {_indexedFiles.Count} blend file(s) under {_searchPath}");
            }
            catch (Exception e)
            {
                Debug.LogError($"{LJBlenderLauncher.LogPrefix} Failed to index blend files: {e.Message}");
            }
        }

        private static string GetDisplayLabel(string file)
        {
            if (!string.IsNullOrEmpty(_searchPath))
            {
                string rooted = _searchPath.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
                if (file.StartsWith(rooted, StringComparison.OrdinalIgnoreCase))
                {
                    return file.Substring(rooted.Length);
                }
            }
            return Path.GetFileName(file);
        }
    }
}
