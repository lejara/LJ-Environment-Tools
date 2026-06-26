using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace LJ.EditorTools
{
    public class LJFileBrowserPanel
    {
        private const int ButtonsPerRow = 4;
        private const float ButtonHeight = 28f;
        private const float RowSpacing = 2f;
        private const int VisibleRows = 3;

        private static readonly string[] _ignoredNames = new[]
        {
            ".autosave",
            "*_autosave_*",
            "*_ver_*"
        };

        private static readonly char[] _pathSeparators = new[] { '\\', '/' };

        private readonly string _title;
        private readonly string _extension;
        private readonly string _fileTypeLabel;
        private readonly string _prefKey;
        private readonly string _logPrefix;
        private readonly Action<string> _onLaunch;

        private string _searchPath;
        private List<string> _indexedFiles;
        private Vector2 _scroll;
        private bool _initialized;
        private bool _expanded = true;

        public LJFileBrowserPanel(string title, string extension, string fileTypeLabel, string prefKey, string logPrefix, Action<string> onLaunch)
        {
            _title = title;
            _extension = extension;
            _fileTypeLabel = fileTypeLabel;
            _prefKey = prefKey;
            _logPrefix = logPrefix;
            _onLaunch = onLaunch;
        }

        public void DrawGUI()
        {
            EnsureInitialized();

            EditorGUI.BeginChangeCheck();
            _expanded = EditorGUILayout.Foldout(_expanded, _title, true, EditorStyles.foldoutHeader);
            if (EditorGUI.EndChangeCheck())
            {
                EditorPrefs.SetBool(_prefKey + ".Expanded", _expanded);
            }
            if (!_expanded)
                return;

            GUILayout.Space(LJEnvironmentTools.FoldoutPadding);

            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUI.BeginChangeCheck();
                string newPath = EditorGUILayout.TextField("Search Path", _searchPath);
                if (EditorGUI.EndChangeCheck())
                {
                    _searchPath = newPath;
                    EditorPrefs.SetString(_prefKey, _searchPath ?? string.Empty);
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
                        EditorPrefs.SetString(_prefKey, _searchPath);
                        IndexFiles();
                    }
                }
            }

            using (new EditorGUI.DisabledScope(string.IsNullOrEmpty(_searchPath) || !Directory.Exists(_searchPath)))
            {
                if (GUILayout.Button($"Index {_fileTypeLabel} Files", GUILayout.Height(24)))
                {
                    IndexFiles();
                }
            }

            if (_indexedFiles == null || _indexedFiles.Count == 0)
            {
                EditorGUILayout.HelpBox($"No {_extension} files indexed yet. Pick a folder and press Index.", MessageType.Info);
                GUILayout.Space(LJEnvironmentTools.FoldoutPadding);
                return;
            }

            EditorGUILayout.LabelField($"Found {_indexedFiles.Count} {_extension} file(s)", EditorStyles.miniLabel);

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
                            _onLaunch?.Invoke(file);
                        }
                    }
                }
            }
            EditorGUILayout.EndScrollView();

            GUILayout.Space(LJEnvironmentTools.FoldoutPadding);
        }

        public void AutoIndexOnLoad()
        {
            EnsureInitialized();
            if (!string.IsNullOrEmpty(_searchPath) && Directory.Exists(_searchPath))
            {
                IndexFiles();
            }
        }

        private void EnsureInitialized()
        {
            if (_initialized)
            {
                return;
            }
            _searchPath = EditorPrefs.GetString(_prefKey, string.Empty);
            _expanded = EditorPrefs.GetBool(_prefKey + ".Expanded", true);
            _initialized = true;
        }

        private void IndexFiles()
        {
            _indexedFiles = new List<string>();

            if (string.IsNullOrEmpty(_searchPath) || !Directory.Exists(_searchPath))
            {
                Debug.LogWarning($"{_logPrefix} Search path is invalid: {_searchPath}");
                return;
            }

            try
            {
                string[] found = Directory.GetFiles(_searchPath, "*" + _extension, SearchOption.AllDirectories);
                foreach (string file in found)
                {
                    string ext = Path.GetExtension(file);
                    if (!string.Equals(ext, _extension, StringComparison.OrdinalIgnoreCase)) continue;
                    if (IsIgnored(file, _searchPath)) continue;
                    _indexedFiles.Add(file);
                }
                _indexedFiles.Sort(StringComparer.OrdinalIgnoreCase);
                Debug.Log($"{_logPrefix} Indexed {_indexedFiles.Count} {_extension} file(s) under {_searchPath}");
            }
            catch (Exception e)
            {
                Debug.LogError($"{_logPrefix} Failed to index {_extension} files: {e.Message}");
            }
        }

        private static bool IsIgnored(string fullPath, string searchPath)
        {
            string rel = fullPath.Length > searchPath.Length
                ? fullPath.Substring(searchPath.Length)
                : fullPath;
            string[] segments = rel.Split(_pathSeparators, StringSplitOptions.RemoveEmptyEntries);
            foreach (string segment in segments)
            {
                foreach (string pattern in _ignoredNames)
                {
                    if (MatchesPattern(segment, pattern)) return true;
                }
            }
            return false;
        }

        private static bool MatchesPattern(string segment, string pattern)
        {
            if (string.IsNullOrEmpty(pattern)) return false;
            bool wildStart = pattern[0] == '*';
            bool wildEnd = pattern.Length > 1 && pattern[pattern.Length - 1] == '*';
            int coreStart = wildStart ? 1 : 0;
            int coreEnd = wildEnd ? pattern.Length - 1 : pattern.Length;
            string core = pattern.Substring(coreStart, coreEnd - coreStart);

            if (wildStart && wildEnd)
            {
                if (core.Length == 0) return true;
                return segment.IndexOf(core, StringComparison.OrdinalIgnoreCase) >= 0;
            }
            if (wildStart) return segment.EndsWith(core, StringComparison.OrdinalIgnoreCase);
            if (wildEnd) return segment.StartsWith(core, StringComparison.OrdinalIgnoreCase);
            return string.Equals(segment, pattern, StringComparison.OrdinalIgnoreCase);
        }
    }
}
