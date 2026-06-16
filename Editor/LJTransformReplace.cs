using System.Collections.Generic;
using LJ.EditorTools;
using UnityEditor;
using UnityEngine;

public static class LJTransformReplace
{
    [MenuItem(LJHotkeys.TransformReplaceMenu)]
    static void TransformReplace()
    {
        GameObject prefabAsset = null;
        var sceneObjects = new List<GameObject>();

        foreach (var obj in Selection.objects)
        {
            var go = obj as GameObject;
            if (go == null)
                continue;

            if (AssetDatabase.Contains(go))
            {
                if (prefabAsset == null &&
                    PrefabUtility.GetPrefabAssetType(go) != PrefabAssetType.NotAPrefab)
                {
                    prefabAsset = go;
                }
            }
            else
            {
                sceneObjects.Add(go);
            }
        }

        if (prefabAsset == null)
        {
            Debug.LogWarning("LJTransformReplace: Select a prefab asset in the Project window.");
            return;
        }

        if (sceneObjects.Count == 0)
        {
            Debug.LogWarning("LJTransformReplace: Select at least one object in the scene.");
            return;
        }

        Undo.IncrementCurrentGroup();
        int undoGroup = Undo.GetCurrentGroup();
        Undo.SetCurrentGroupName("LJ Transform Replace");

        var newSelection = new List<GameObject>();

        foreach (var sceneObj in sceneObjects)
        {
            var source = sceneObj.transform;
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefabAsset, sceneObj.scene);
            Undo.RegisterCreatedObjectUndo(instance, "LJ Transform Replace");

            if (source.parent != null)
                Undo.SetTransformParent(instance.transform, source.parent, "LJ Transform Replace");

            instance.transform.SetSiblingIndex(source.GetSiblingIndex());
            instance.transform.localPosition = source.localPosition;
            instance.transform.localRotation = source.localRotation;
            instance.transform.localScale = source.localScale;

            Undo.DestroyObjectImmediate(sceneObj);
            newSelection.Add(instance);
        }

        Selection.objects = newSelection.ToArray();
        Undo.CollapseUndoOperations(undoGroup);
    }
}
