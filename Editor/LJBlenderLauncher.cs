using System;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using Debug = UnityEngine.Debug;

namespace LJ.EditorTools
{
    public static class LJBlenderLauncher
    {
        public const string LogPrefix = "[LJ Environment Tools]";
        private const string BlenderPathPrefKey = "LJ.BlenderPath";
        private const string TempScriptFileName = "lj_blender_import.py";

        private static readonly string[] CommonInstallRoots =
        {
            @"C:\Program Files\Blender Foundation",
            @"C:\Program Files (x86)\Blender Foundation",
        };

        public static void ExportAndOpen()
        {
            string fbxPath = LJFbxExporter.ExportSelection();
            if (string.IsNullOrEmpty(fbxPath))
            {
                return;
            }

            OpenFbxInBlender(fbxPath);
        }

        public static void OpenFbxInBlender(string fbxPath)
        {
            string blenderPath = ResolveBlenderPath();
            if (string.IsNullOrEmpty(blenderPath))
            {
                Debug.LogError($"{LogPrefix} Blender executable not configured. Aborting open.");
                return;
            }

            string scriptPath = WriteImportScript(fbxPath);

            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = blenderPath,
                    Arguments = $"--python \"{scriptPath}\"",
                    UseShellExecute = false,
                    CreateNoWindow = false,
                };
                Process.Start(psi);
                Debug.Log($"{LogPrefix} Launched Blender with: {fbxPath}");
            }
            catch (Exception e)
            {
                Debug.LogError($"{LogPrefix} Failed to launch Blender: {e.Message}");
                EditorPrefs.DeleteKey(BlenderPathPrefKey);
            }
        }

        public static void LaunchBlendFile(string blendPath)
        {
            if (string.IsNullOrEmpty(blendPath) || !File.Exists(blendPath))
            {
                Debug.LogError($"{LogPrefix} Blend file not found: {blendPath}");
                return;
            }

            string blenderPath = ResolveBlenderPath();
            if (string.IsNullOrEmpty(blenderPath))
            {
                Debug.LogError($"{LogPrefix} Blender executable not configured. Aborting open.");
                return;
            }

            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = blenderPath,
                    Arguments = $"\"{blendPath}\"",
                    UseShellExecute = false,
                    CreateNoWindow = false,
                };
                Process.Start(psi);
                Debug.Log($"{LogPrefix} Launched Blender with: {blendPath}");
            }
            catch (Exception e)
            {
                Debug.LogError($"{LogPrefix} Failed to launch Blender: {e.Message}");
                EditorPrefs.DeleteKey(BlenderPathPrefKey);
            }
        }

        private static string ResolveBlenderPath()
        {
            string found = AutoDetect();
            if (!string.IsNullOrEmpty(found))
            {
                string cached = EditorPrefs.GetString(BlenderPathPrefKey, string.Empty);
                if (!string.Equals(cached, found, StringComparison.OrdinalIgnoreCase))
                {
                    EditorPrefs.SetString(BlenderPathPrefKey, found);
                    Debug.Log($"{LogPrefix} Detected Blender at: {found}");
                }
                return found;
            }

            string cachedFallback = EditorPrefs.GetString(BlenderPathPrefKey, string.Empty);
            if (!string.IsNullOrEmpty(cachedFallback) && File.Exists(cachedFallback))
            {
                return cachedFallback;
            }

            string picked = EditorUtility.OpenFilePanel("Locate blender.exe", "C:/Program Files/Blender Foundation", "exe");
            if (string.IsNullOrEmpty(picked) || !File.Exists(picked))
            {
                return null;
            }

            EditorPrefs.SetString(BlenderPathPrefKey, picked);
            return picked;
        }

        private static string AutoDetect()
        {
            string bestExe = null;
            Version bestVersion = null;

            foreach (string root in CommonInstallRoots)
            {
                if (!Directory.Exists(root))
                {
                    continue;
                }

                foreach (string dir in Directory.GetDirectories(root, "Blender *"))
                {
                    string exe = Path.Combine(dir, "blender.exe");
                    if (!File.Exists(exe))
                    {
                        continue;
                    }

                    string versionPart = Path.GetFileName(dir).Substring("Blender ".Length).Trim();
                    if (!Version.TryParse(NormalizeVersion(versionPart), out Version version))
                    {
                        continue;
                    }

                    if (bestVersion == null || version > bestVersion)
                    {
                        bestVersion = version;
                        bestExe = exe;
                    }
                }
            }

            return bestExe;
        }

        private static string NormalizeVersion(string raw)
        {
            return raw.Contains(".") ? raw : raw + ".0";
        }

        private static string WriteImportScript(string fbxPath)
        {
            string escaped = fbxPath.Replace("\\", "\\\\").Replace("\"", "\\\"");
            string py =
                "import bpy\n" +
                "bpy.ops.wm.read_homefile(use_empty=True)\n" +
                $"bpy.ops.import_scene.fbx(filepath=\"{escaped}\")\n";

            string path = Path.Combine(Path.GetTempPath(), TempScriptFileName);
            File.WriteAllText(path, py);
            return path;
        }

        [MenuItem("Tools/LJ/Reset Blender Path")]
        private static void ResetBlenderPath()
        {
            EditorPrefs.DeleteKey(BlenderPathPrefKey);
            Debug.Log($"{LogPrefix} Cleared Blender path. You'll be re-prompted on next launch.");
        }
    }
}
