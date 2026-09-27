# LJ Stylized Grass (HDRP 17.3 / Unity 6000.3)

GPU-instanced grass: `Graphics.RenderMeshInstanced` per camera, per chunk. No GameObject per blade and no CPU animation per blade; wind runs in the Shader Graph vertex stage.

## Files
| Path | Purpose |
|---|---|
| `Runtime/StylizedGrassRenderer.cs` | Placement, chunking, per-camera drawing (builds-safe) |
| `Editor/StylizedGrassRendererEditor.cs` | Inspector, Regenerate/Clear, checks, scene gizmos, menu items (editor-only folder) |
| `Shaders/SG_StylizedGrass.shadergraph` | HDRP Lit graph, double-sided (flipped normals) |
| `Shaders/LJ_StylizedGrass.hlsl` | Custom functions: wind (vertex) and colour (fragment) |
| `Samples/` | Sample blade mesh + prefab, `M_StylizedGrass` material, `T_GrassDensity_Sample` map |

## Setup
1. **Mesh**: pivot at the blade root, local +Y up, intermediate vertices for bending. Bake transforms into the mesh (child transforms in the prefab are ignored). Root-to-tip weight = `positionOS.y / mesh.bounds.max.y`. Alternative: author UV0.y from 0 (root) to 1 (tip) and set **Height From UV** = 1 on the material.
2. **Prefab**: MeshFilter + MeshRenderer with a material using `LJ Environment Tools/SG_StylizedGrass`. Assign it to **Grass Prefab** (or use **Material Override**).
3. **Material**: **Enable GPU Instancing** must be on (the inspector offers a fix button). Double-sided is on with flipped normals. Alpha clipping stays off for solid blades; to use a textured blade, assign **Blade Texture** and tick Alpha Clipping in Surface Options. Wind: Direction (XZ), Strength, Speed, Noise Scale, Variation, Flutter, Bend Exponent. Colour: Base/Tip, Gradient Power, Variation Colour/Amount/Scale, Brightness Variation, Root Darkening.
4. **Ground**: put ground meshes (Mesh Collider) and Terrains (Terrain Collider) on the layers in **Ground Layers**. A dedicated "Ground" layer is recommended. Rays start **Raycast Height** above this object's Y and go **Raycast Depth** below it. No hit, or a slope steeper than **Max Slope**, means no blade.
5. Add via **GameObject > LJ Environment Tools > Stylized Grass**, then place it at ground height.

## Density map
* Grayscale: white = full density, black = none, gray = proportional. Each candidate is accepted with probability `map × noise`. Candidate count = `Density × Density Multiplier × tile area`. Black always stays empty.
* **Import**: sRGB **off** (linear data), Compression None, no mipmaps, Wrap Repeat. Readable is recommended (exact CPU read); non-readable maps use a GPU copy, which gives wrong gray values if sRGB is on. Use **Assets > LJ Environment Tools > Configure As Grass Density Map**.
* UV (0,0) = texture's bottom-left corner = the tile's local −X/−Z corner. U runs along local +X, V along local +Z (the image is seen from above, with its top toward +Z). Gizmos show U in red and V in blue.
* **Repeat Per Tile** (default) or **Stretch Across Area**. Random per-tile 90° rotations and offsets are optional and off by default.
* The map is read only when placement is generated, never per frame.

## Regeneration
Placement is regenerated when a placement setting or this transform changes (**Auto Regenerate**), or when you click **Regenerate**. Render-only settings (shadows, draw distance, fade) never regenerate. Changing the ground or re-painting the map in an external tool needs a manual **Regenerate**. At runtime, data is built once on the first rendered frame.

## Performance controls
Density / Multiplier, Tile Count / Area, **Chunk Size** (smaller chunks cull more precisely but add draw calls), **Max Draw Distance** + **Fade Band** (blades shrink out before the chunk cut-off), **Shadow Casting** (the largest cost; consider Off or a shorter distance), **Motion Vectors**, and **Max Blades** as a safety cap. The inspector shows blade, candidate and chunk counts, plus generation time.
