using System;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEngine;
using Debug = UnityEngine.Debug;

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

            if (GUILayout.Button("Open VS Code 💻", GUILayout.Height(28)))
            {
                OpenVSCode();
            }

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

        private static void OpenVSCode()
        {
            string projectRoot = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = "/c code .",
                    WorkingDirectory = projectRoot,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                Process.Start(psi);
                Debug.Log($"[LJBrowser] Launched VS Code at: {projectRoot}");
            }
            catch (Exception e)
            {
                Debug.LogError($"[LJBrowser] Failed to launch VS Code: {e.Message}");
            }
        }
    }
}
