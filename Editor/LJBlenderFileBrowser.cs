using UnityEditor;

namespace LJ.EditorTools
{
    public static class LJBlenderFileBrowser
    {
        private static readonly LJFileBrowserPanel _panel = new LJFileBrowserPanel(
            title: "Blender File Browser 🏝️",
            extension: ".blend",
            fileTypeLabel: "Blender",
            prefKey: "LJ.BlenderBrowser.SearchPath",
            logPrefix: LJBlenderLauncher.LogPrefix,
            onLaunch: LJBlenderLauncher.LaunchBlendFile
        );

        public static void DrawGUI() => _panel.DrawGUI();

        public static void RefreshIndex() => _panel.RefreshIndex();

        [InitializeOnLoadMethod]
        private static void AutoIndexOnEditorLoad() => _panel.AutoIndexOnLoad();
    }
}
