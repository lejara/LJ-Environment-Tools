using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Text;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace LJ.EditorTools
{
    // Talks to Blender instances running the LJ addon's Server (BlenderAddon/unity_bridge.py).
    // Each instance advertises itself as %TEMP%/LJBridge/<pid>.json.
    public static class LJBlenderBridge
    {
        private const string LogPrefix = LJBlenderLauncher.LogPrefix;
        private const int TimeoutMs = 3000;

        private static readonly string BridgeDir = Path.Combine(Path.GetTempPath(), "LJBridge");

        [Serializable]
        public class Instance
        {
            public int pid;
            public int port;
            public string file;
            public string version;

            public string Label => $"Blender {version} – {file} (pid {pid})";
        }

        [Serializable]
        private class Response
        {
            public bool ok;
            public string error;
        }

        [Serializable]
        private class ImportRequest
        {
            public string cmd = "import_fbx";
            public string path;
        }

        public static List<Instance> FindInstances()
        {
            var instances = new List<Instance>();
            if (!Directory.Exists(BridgeDir))
            {
                return instances;
            }

            foreach (string infoPath in Directory.GetFiles(BridgeDir, "*.json"))
            {
                Instance instance;
                try
                {
                    instance = JsonUtility.FromJson<Instance>(File.ReadAllText(infoPath));
                }
                catch (Exception)
                {
                    continue;
                }

                if (instance == null || instance.port <= 0)
                {
                    continue;
                }

                if (!IsProcessAlive(instance.pid))
                {
                    // Left behind by a crashed Blender.
                    TryDelete(infoPath);
                    continue;
                }

                instances.Add(instance);
            }

            return instances;
        }

        public static void ExportTo(Instance instance)
        {
            string fbxPath = LJFbxExporter.ExportSelection();
            if (string.IsNullOrEmpty(fbxPath))
            {
                return;
            }

            SendFbx(instance, Path.GetFullPath(fbxPath));
        }

        public static bool SendFbx(Instance instance, string fbxPath)
        {
            string payload = JsonUtility.ToJson(new ImportRequest { path = fbxPath });

            try
            {
                using (var client = new TcpClient())
                {
                    client.SendTimeout = TimeoutMs;
                    client.ReceiveTimeout = TimeoutMs;
                    if (!client.ConnectAsync("127.0.0.1", instance.port).Wait(TimeoutMs))
                    {
                        Debug.LogError($"{LogPrefix} Timed out connecting to {instance.Label}.");
                        return false;
                    }

                    NetworkStream stream = client.GetStream();
                    byte[] bytes = Encoding.UTF8.GetBytes(payload);
                    stream.Write(bytes, 0, bytes.Length);
                    client.Client.Shutdown(SocketShutdown.Send);

                    string reply = ReadToEnd(stream);
                    Response response = JsonUtility.FromJson<Response>(reply);
                    if (response == null || !response.ok)
                    {
                        Debug.LogError($"{LogPrefix} Blender rejected the FBX: {response?.error ?? reply}");
                        return false;
                    }
                }
            }
            catch (Exception e)
            {
                Debug.LogError($"{LogPrefix} Failed to send FBX to {instance.Label}: {e.Message}");
                return false;
            }

            Debug.Log($"{LogPrefix} Sent {fbxPath} to {instance.Label}");
            return true;
        }

        private static string ReadToEnd(NetworkStream stream)
        {
            var buffer = new byte[4096];
            var sb = new StringBuilder();
            int read;
            while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
            {
                sb.Append(Encoding.UTF8.GetString(buffer, 0, read));
            }
            return sb.ToString();
        }

        private static bool IsProcessAlive(int pid)
        {
            try
            {
                using (Process p = Process.GetProcessById(pid))
                {
                    return !p.HasExited;
                }
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static void TryDelete(string path)
        {
            try
            {
                File.Delete(path);
            }
            catch (Exception)
            {
            }
        }
    }
}
