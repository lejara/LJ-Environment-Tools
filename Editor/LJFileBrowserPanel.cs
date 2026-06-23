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

            _expanded = EditorGUILayout.Foldout(_expanded, _title, true, EditorStyles.foldoutHeader);
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
                    if (string.Equals(ext, _extension, StringComparison.OrdinalIgnoreCase))
                    {
                        _indexedFiles.Add(file);
                    }
                }
                _indexedFiles.Sort(StringComparer.OrdinalIgnoreCase);
                Debug.Log($"{_logPrefix} Indexed {_indexedFiles.Count} {_extension} file(s) under {_searchPath}");
            }
            catch (Exception e)
            {
                Debug.LogError($"{_logPrefix} Failed to index {_extension} files: {e.Message}");
            }
        }
    }
}
