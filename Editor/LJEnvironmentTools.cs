using UnityEditor;
using UnityEngine;

namespace LJ.EditorTools
{
    public class LJEnvironmentTools : EditorWindow
    {
        private const string WindowTitle = "LJ Environment Tools";

        private Vector2 _scroll;

        [MenuItem("Tools/LJ/Environment Tools")]
        public static void ShowWindow()
        {
            GetWindow<LJEnvironmentTools>(WindowTitle);
        }

        private void OnGUI()
        {
            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            GUILayout.Space(8);
            GUILayout.Label("Exportor 🏃‍♂️", EditorStyles.boldLabel);

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


            GUILayout.Space(48);
            LJBlenderFileBrowser.DrawGUI();

            GUILayout.Space(48);
            LJAutoPrefabCreator.DrawGUI();

            GUILayout.Space(48);
            HotKeysCheatsheet.DrawGUI();

            GUILayout.Space(48);

            EditorGUILayout.EndScrollView();
        }
    }
}
