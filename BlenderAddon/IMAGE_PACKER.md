# LJ Image Packer

Included in the existing LJ Environment Tools addon. Install the rebuilt
`Lj Environment Tools.zip`, then open **3D View > Sidebar (N) > LJ > LJ Image Packer**.

1. Set the global output folder and press **+** to add a preset.
2. Name the preset. Its name is used for the exported PNG.
3. Set its width, height and bit depth (8-bit by default, or 16-bit).
4. For each output channel, pick an image already loaded in Blender and choose
   R, G, B, A, or RGB to Grayscale. Leave the image empty to use its constant
   value (0–1, default 0 for all four channels).
5. Optionally set a preset output folder; an empty field uses the global folder.
6. Use the export icon on a preset row, or **Export All Presets**.

Exports overwrite matching files. Missing output folders are created. Duplicate
output paths in a batch are rejected before exporting. `//` paths resolve from
the saved blend file; save the blend first when using relative paths.

**Load into Blender** defaults to off. Enable it to load exported PNGs or refresh
existing images using the same paths. Loaded results use Non-Color and Channel
Packed alpha, and remain in the blend file even without material users. Blender
may suffix the image datablock name when another image already owns that name;
the exported filename remains the preset name.

Presets, source references and settings are stored with the scene in the blend
file. Exporting also remembers the global folder and loading toggle as addon
defaults for new blend files, following the other LJ tools.

Sources are resized using bilinear interpolation without editing their pixels
or dimensions. Grayscale uses weights 0.2126 R + 0.7152 G + 0.0722 B. Packing
uses Blender's exposed pixel-buffer values, clamps output to 0–1, and applies
no display transform or extra gamma conversion. RGB is preserved even when
alpha is zero. 16-bit PNG output retains 16-bit precision from float sources;
it cannot recover precision absent from an 8-bit source.

The first version supports still file images and generated images, including
packed still images. Movies, image sequences, UDIMs and render results are not
supported. Export runs synchronously, with progress and per-preset error reports.

## Verification

Run with Blender 5.1:

```powershell
& 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe' --background --factory-startup --python-exit-code 1 --python 'BlenderAddon/tests/test_image_packer.py'
```

The integration test checks actual PNG bytes and 16-bit precision, image loading
and refresh, source preservation, resizing, output paths, batch collisions,
blend-file persistence, and addon registration. It writes only temporary test
artifacts and does not save user preferences.
