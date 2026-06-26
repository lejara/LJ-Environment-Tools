using System;
using System.Diagnostics;
using UnityEditor;
using Debug = UnityEngine.Debug;

namespace LJ.EditorTools
{
    public static class LJSubstancePainterFileBrowser
    {
        private const string LogPrefix = "[LJ Environment Tools]";

        private static readonly LJFileBrowserPanel _panel = new LJFileBrowserPanel(
            title: "Substance Painter File Browser 🎨",
            extension: ".spp",
            fileTypeLabel: "Substance Painter",
            prefKey: "LJ.SubstancePainterBrowser.SearchPath",
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
                Debug.Log($"{LogPrefix} Launched Substance Painter with: {path}");
            }
            catch (Exception e)
            {
                Debug.LogError($"{LogPrefix} Failed to launch Substance Painter: {e.Message}");
            }
        }
    }
}
