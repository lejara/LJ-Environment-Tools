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

        [MenuItem("Tools/LJ/Environment Tools")]
        public static void ShowWindow()
        {
            GetWindow<LJEnvironmentTools>(WindowTitle);
        }

        private void OnEnable()
        {
            _exporterExpanded = EditorPrefs.GetBool(ExporterExpandedPrefKey, true);
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
