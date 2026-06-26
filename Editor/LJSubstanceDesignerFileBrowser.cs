using System;
using System.Diagnostics;
using UnityEditor;
using Debug = UnityEngine.Debug;

namespace LJ.EditorTools
{
    public static class LJSubstanceDesignerFileBrowser
    {
        private const string LogPrefix = "[LJ Environment Tools]";

        private static readonly LJFileBrowserPanel _panel = new LJFileBrowserPanel(
            title: "Substance Designer File Browser 🧱",
            extension: ".sbs",
            fileTypeLabel: "Substance Designer",
            prefKey: "LJ.SubstanceDesignerBrowser.SearchPath",
            logPrefix: LogPrefix,
            onLaunch: LaunchFile
        );

        public static void DrawGUI() => _panel.DrawGUI();

        public static void RefreshIndex() => _panel.RefreshIndex();

        [InitializeOnLoadMethod]
        private static void AutoIndexOnEditorLoad() => _panel.AutoIndexOnLoad();

        private static void LaunchFile(string path)
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = path,
                    UseShellExecute = true,
                });
                Debug.Log($"{LogPrefix} Launched Substance Designer with: {path}");
            }
            catch (Exception e)
            {
                Debug.LogError($"{LogPrefix} Failed to launch Substance Designer: {e.Message}");
            }
        }
    }
}
