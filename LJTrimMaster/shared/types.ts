/**
 * Enums and serialization shapes shared across the main and renderer processes.
 * Keep this file free of imports so both bundles can pull it in cheaply.
 */

/** A preset either passes one map through, or packs several into one image. */
export type PresetMode = 'copy' | 'pack'

/** Output channel of a packed image. */
export type Channel = 'R' | 'G' | 'B' | 'A'

/** Channel to sample from a source map. `L` means luminance of RGB. */
export type SourceChannel = 'R' | 'G' | 'B' | 'A' | 'L'

/**
 * Tangent-space handedness of a normal map.
 *
 * OpenGL encodes +Y upward (Unity, Substance's Unity preset); DirectX encodes
 * it downward (Unreal). It decides the sign of the rotation applied to the
 * (R,G) vector when a trim is rotated — get it wrong and rotated trims light
 * backwards.
 */
export type NormalConvention = 'OpenGL' | 'DirectX'

export const NORMAL_CONVENTIONS: NormalConvention[] = ['OpenGL', 'DirectX']

/** Encoding of a written file. */
export type OutputFormat = 'PNG_RGBA' | 'PNG_RGB' | 'TGA' | 'JPG'

export const OUTPUT_FORMATS: OutputFormat[] = ['PNG_RGBA', 'PNG_RGB', 'TGA', 'JPG']

/** File extension written for each format. */
export const FORMAT_EXTENSIONS: Record<OutputFormat, string> = {
  PNG_RGBA: 'png',
  PNG_RGB: 'png',
  TGA: 'tga',
  JPG: 'jpg'
}

// --- Serialization shapes -------------------------------------------------
// These are the on-disk shape of projectData.json and the payloads that cross
// IPC. The renderer/models classes hydrate from and dehydrate to these.

export interface SerializedVec2 {
  x: number
  y: number
}

export interface SerializedResolution {
  width: number
  height: number
}

export interface SerializedTransform {
  /** Normalized 0-1 position of the trim's centre within the sheet. */
  position: SerializedVec2
  /** Normalized 0-1 size of the trim relative to the sheet. Sign flips the axis. */
  scale: SerializedVec2
  /** Degrees, counter-clockwise. */
  rotation: number
}

export interface SerializedCrop {
  /** Normalized 0-0.5 inset taken off the left AND right edges of the source. */
  x: number
  /** Normalized 0-0.5 inset taken off the top AND bottom edges of the source. */
  y: number
}

export interface SerializedTrimImage {
  id: string
  assetBaseName: string
  transform: SerializedTransform
  crop: SerializedCrop
}

export interface SerializedSheet {
  id: string
  name: string
  resolution: SerializedResolution
  enabledPresetNames: string[]
  items: SerializedTrimImage[]
}

export interface SerializedProjectDefaults {
  defaultTrimResolution: SerializedResolution
}

export interface SerializedProjectData {
  version: string
  defaults: SerializedProjectDefaults
  sheets: SerializedSheet[]
}

/** An asset as it crosses IPC — map name to absolute path on disk. */
export interface SerializedAsset {
  baseName: string
  mapPaths: Record<string, string>
  primaryMap: string
}

export interface SerializedMapConfig {
  /** Every delimiter that may separate a base name from its map suffix. */
  suffixDelims: string[]
  knownMaps: string[]
}

export interface SerializedChannelSpec {
  source?: string
  fromChannel?: SourceChannel
  invert?: boolean
  fallback?: number
  constant?: number
}

/**
 * One texture a preset writes. A preset may write several — that is what lets
 * a single "Unity HDRP" preset produce BaseColor, Normal and MaskMap together.
 */
export interface SerializedPresetOutput {
  mode: PresetMode
  outputSuffix: string
  format: OutputFormat
  /** copy mode only — the map name to pass through. */
  source?: string
  /** Only consulted when the source map is a Normal. */
  normalConvention?: NormalConvention
  /** pack mode only. */
  channels?: Partial<Record<Channel, SerializedChannelSpec>>
}

export interface SerializedPreset {
  name: string
  outputs: SerializedPresetOutput[]
}

/** Result of a project open/new — everything the renderer needs to boot the editor. */
export interface OpenProjectResult {
  rootPath: string
  data: SerializedProjectData
}

/** Everything a refresh reloads. */
export interface RefreshResult {
  mapConfig: SerializedMapConfig
  presets: SerializedPreset[]
  assets: SerializedAsset[]
  /** Non-fatal problems worth showing the user (duplicate preset names, bad YAML). */
  warnings: string[]
}

/** Current project version stamp. Bump when the on-disk shape changes. */
export const PROJECT_DATA_VERSION = '1'
