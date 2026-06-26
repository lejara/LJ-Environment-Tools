using UnityEditor;
using UnityEngine;

namespace LJ.EditorTools
{
    public class LJBrowser : EditorWindow
    {
        private const string WindowTitle = "LJ Browser";

        private Vector2 _scroll;

        [MenuItem("Tools/LJ/Browser")]
        public static void ShowWindow()
        {
            GetWindow<LJBrowser>(WindowTitle);
        }

        private void OnGUI()
        {
            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            GUILayout.Space(8);

            LJBlenderFileBrowser.DrawGUI();

            GUILayout.Space(8);
            LJSubstancePainterFileBrowser.DrawGUI();

            GUILayout.Space(8);
            LJSubstanceDesignerFileBrowser.DrawGUI();

            GUILayout.Space(8);
            if (GUILayout.Button("Refresh Index 🔄", GUILayout.Height(28)))
            {
                LJBlenderFileBrowser.RefreshIndex();
                LJSubstancePainterFileBrowser.RefreshIndex();
                LJSubstanceDesignerFileBrowser.RefreshIndex();
            }

            GUILayout.Space(8);
            EditorGUILayout.EndScrollView();
        }
    }
}
