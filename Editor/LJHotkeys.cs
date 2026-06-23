using UnityEditor;
using UnityEngine;

namespace LJ.EditorTools
{
    public static class LJHotkeys
    {
        public const string DeparentSelectedMenu = "Edit/Deparent Selected %e";
        public const string TransformReplaceMenu = "Edit/LJ Transform Replace %;";

        public struct Entry
        {
            public string Name;
            public string Shortcut;
            public string Description;
        }

        public static readonly Entry[] All =
        {
            new Entry
            {
                Name = "Deparent Selected",
                Shortcut = "Ctrl + E",
                Description = "Move selected objects out of their parent, placing them as the next sibling.",
            },
            new Entry
            {
                Name = "LJ Transform Replace",
                Shortcut = "Ctrl + ;",
                Description = "Replace selected scene objects with the selected prefab, keeping transform & sibling order.",
            },
        };
    }

    public static class HotKeysCheatsheet
    {
        private const string ExpandedPrefKey = "LJ.HotKeysCheatsheet.Expanded";

        private static bool _initialized;
        private static bool _expanded = true;

        public static void DrawGUI()
        {
            if (!_initialized)
            {
                _expanded = EditorPrefs.GetBool(ExpandedPrefKey, true);
                _initialized = true;
            }

            EditorGUI.BeginChangeCheck();
            _expanded = EditorGUILayout.Foldout(_expanded, "HotKeys Cheatsheet ⌨️", true, EditorStyles.foldoutHeader);
            if (EditorGUI.EndChangeCheck())
            {
                EditorPrefs.SetBool(ExpandedPrefKey, _expanded);
            }
            if (!_expanded)
                return;

            GUILayout.Space(LJEnvironmentTools.FoldoutPadding);

            var shortcutStyle = new GUIStyle(EditorStyles.boldLabel) { fixedWidth = 100 };

            foreach (var entry in LJHotkeys.All)
            {
                using (new EditorGUILayout.HorizontalScope(EditorStyles.helpBox))
                {
                    EditorGUILayout.LabelField(entry.Shortcut, shortcutStyle, GUILayout.Width(100));
                    using (new EditorGUILayout.VerticalScope())
                    {
                        EditorGUILayout.LabelField(entry.Name, EditorStyles.boldLabel);
                        EditorGUILayout.LabelField(entry.Description, EditorStyles.wordWrappedLabel);
                    }
                }
            }

            GUILayout.Space(LJEnvironmentTools.FoldoutPadding);
        }
    }
}
