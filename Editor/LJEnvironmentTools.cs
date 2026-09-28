using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace LJ.EditorTools
{
    public class LJEnvironmentTools : EditorWindow
    {
        private const string WindowTitle = "LJ Environment Tools";
        private const string ExporterExpandedPrefKey = "LJ.EnvTools.ExporterExpanded";
        public const int FoldoutPadding = 24;

        private Vector2 _scroll;
        private bool _exporterExpanded = true;
        private List<LJBlenderBridge.Instance> _blenderInstances = new List<LJBlenderBridge.Instance>();
        private int _blenderInstanceIndex;

        [MenuItem("Tools/LJ/Environment Tools")]
        public static void ShowWindow()
        {
            GetWindow<LJEnvironmentTools>(WindowTitle);
        }

        private void OnEnable()
        {
            _exporterExpanded = EditorPrefs.GetBool(ExporterExpandedPrefKey, true);
            RefreshBlenderInstances();
        }

        private void OnFocus()
        {
            RefreshBlenderInstances();
        }

        private void RefreshBlenderInstances()
        {
            int previousPid = _blenderInstanceIndex < _blenderInstances.Count ? _blenderInstances[_blenderInstanceIndex].pid : -1;
            _blenderInstances = LJBlenderBridge.FindInstances();
            int kept = _blenderInstances.FindIndex(i => i.pid == previousPid);
            _blenderInstanceIndex = kept >= 0 ? kept : 0;
        }

        private void DrawRunningBlenderGUI(int selectedCount)
        {
            GUILayout.Space(8);
            EditorGUILayout.LabelField("Running Blender", EditorStyles.boldLabel);

            using (new EditorGUILayout.HorizontalScope())
            {
                if (_blenderInstances.Count == 0)
                {
                    EditorGUILayout.HelpBox("No Blender instances found.", MessageType.Info);
                }
                else
                {
                    string[] labels = _blenderInstances.Select(i => i.Label).ToArray();
                    _blenderInstanceIndex = EditorGUILayout.Popup(_blenderInstanceIndex, labels);
                }

                if (GUILayout.Button("Refresh", GUILayout.Width(64)))
                {
                    RefreshBlenderInstances();
                }
            }

            using (new EditorGUI.DisabledScope(selectedCount == 0 || _blenderInstances.Count == 0))
            {
                if (GUILayout.Button("Export to Running Blender 🔗", GUILayout.Height(28)))
                {
                    LJBlenderBridge.ExportTo(_blenderInstances[_blenderInstanceIndex]);
                }
            }
        }

        private void OnSelectionChange()
        {
            Repaint();
        }

        private void OnGUI()
        {
            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            GUILayout.Space(8);

            EditorGUI.BeginChangeCheck();
            bool verbose = EditorGUILayout.ToggleLeft("Verbose Logging", LJFbxExporter.VerboseLogging);
            if (EditorGUI.EndChangeCheck())
            {
                LJFbxExporter.VerboseLogging = verbose;
            }

            GUILayout.Space(8);
            EditorGUI.BeginChangeCheck();
            _exporterExpanded = EditorGUILayout.Foldout(_exporterExpanded, "Exportor 🏃‍♂️", true, EditorStyles.foldoutHeader);
            if (EditorGUI.EndChangeCheck())
            {
                EditorPrefs.SetBool(ExporterExpandedPrefKey, _exporterExpanded);
            }
            if (_exporterExpanded)
            {
                GUILayout.Space(FoldoutPadding);

                int count = Selection.gameObjects.Length;
                EditorGUILayout.LabelField("Selected:", count == 0 ? "Nothing" : $"{count} object(s)");

                using (new EditorGUI.DisabledScope(count == 0))
                {
                    if (GUILayout.Button("Export Selection to FBX", GUILayout.Height(28)))
                    {
                        LJFbxExporter.ExportSelection();
                    }

                    if (GUILayout.Button("Export To Blender 📤", GUILayout.Height(28)))
                    {
                        LJBlenderLauncher.ExportAndOpen();
                    }
                }

                DrawRunningBlenderGUI(count);

                GUILayout.Space(FoldoutPadding);
            }


            GUILayout.Space(8);
            LJAutoPrefabCreator.DrawGUI();

            GUILayout.Space(8);
            LJAutoMaterialCreator.DrawGUI();

            GUILayout.Space(8);
            HotKeysCheatsheet.DrawGUI();

            GUILayout.Space(8);

            EditorGUILayout.EndScrollView();
        }
    }
}
