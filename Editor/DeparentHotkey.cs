using UnityEditor;
using UnityEngine;

public static class AutoPlaceNewObjects
{
    [MenuItem("Edit/Deparent Selected %e")]
    static void DeparentSelected()
    {
        var transforms = Selection.transforms;
        if (transforms == null || transforms.Length == 0)
            return;

        Undo.RecordObjects(transforms, "Deparent Selected");

        foreach (var selected in transforms)
        {
            if (selected.parent == null)
                continue;

            var oldParent = selected.parent;
            int targetIndex = oldParent.GetSiblingIndex() + 1;

            Undo.SetTransformParent(selected, oldParent.parent, "Deparent Selected");
            selected.SetSiblingIndex(targetIndex);

            if (selected.GetComponents<Component>().Length == 1)
                selected.localScale = Vector3.one;
        }
    }
}
