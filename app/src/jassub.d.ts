// jassub 无官方类型声明，按需补充
declare module 'jassub' {
  interface JASSUBOptions {
    video: HTMLVideoElement
    subContent?: string
    subUrl?: string
    workerUrl?: string
    wasmUrl?: string
    legacyWasmUrl?: string
    fallbackFont?: string
    fonts?: (ArrayBuffer | Uint8Array | string)[]
    availableFonts?: Record<string, Uint8Array>
    timeOffset?: number
    onDemand?: boolean
    debug?: boolean
    prescaleFactor?: number
    dropAllAnimations?: boolean
    targetFps?: number
    libassMemoryLimit?: number
    libassGlyphLimit?: number
  }

  export default class JASSUB {
    constructor(options: JASSUBOptions)
    setTrack(content: string): void
    setTrackByUrl(url: string): void
    freeTrack(): void
    resize(width?: number, height?: number, top?: number, left?: number): void
    setCurrentTime(time: number): void
    destroy(): void
  }
}

declare module 'jassub/dist/*' {
  const url: string
  export default url
}
