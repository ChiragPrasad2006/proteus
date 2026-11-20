import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { Resvg } from '@resvg/resvg-js'
import sharp from 'sharp'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = path.join(root, 'art-src', 'proteus-engraving.svg')
const outputDir = path.join(root, 'public', 'art')
const source = await fs.readFile(sourcePath, 'utf8')

const viewBox = source.match(/viewBox="([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"/)
if (!viewBox) throw new Error('The master SVG must declare a viewBox.')
const viewWidth = Number(viewBox[3])
const viewHeight = Number(viewBox[4])
if (!Number.isFinite(viewWidth) || !Number.isFinite(viewHeight)) {
  throw new Error('The master SVG viewBox is invalid.')
}

await fs.mkdir(outputDir, { recursive: true })

/**
 * resvg parses the 21,000-path engraving without librsvg's legacy limits.
 * `fitTo.width` produces the requested square raster while preserving the
 * artwork's original 1448 × 1448 viewBox.
 */
function renderSvg(width) {
  const renderer = new Resvg(source, {
    background: '#ffffff',
    fitTo: { mode: 'width', value: width },
  })
  return renderer.render().asPng()
}

async function writeFullRasters() {
  const full2x = await renderSvg(2400)
  await sharp(full2x)
    .flatten({ background: '#ffffff' })
    .webp({ quality: 85, effort: 6 })
    .toFile(path.join(outputDir, 'proteus-full@2x.webp'))

  const full = await renderSvg(1200)
  await sharp(full)
    .flatten({ background: '#ffffff' })
    .webp({ quality: 82, effort: 6 })
    .toFile(path.join(outputDir, 'proteus-full.webp'))

  const mobile = await renderSvg(800)
  await sharp(mobile)
    .flatten({ background: '#ffffff' })
    .webp({ quality: 80, effort: 6 })
    .toFile(path.join(outputDir, 'proteus-full-800.webp'))

  // Luminance as alpha: black engraving, transparent paper. Used on ink surfaces.
  await sharp(full)
    .flatten({ background: '#ffffff' })
    .greyscale()
    .ensureAlpha(1)
    .raw()
    .toBuffer({ resolveWithObject: true })
    .then(async ({ data, info }) => {
      const rgba = Buffer.alloc(info.width * info.height * 4)
      for (let sourceIndex = 0, targetIndex = 0; sourceIndex < data.length; sourceIndex += info.channels, targetIndex += 4) {
        const luminance = data[sourceIndex]
        rgba[targetIndex] = 0
        rgba[targetIndex + 1] = 0
        rgba[targetIndex + 2] = 0
        rgba[targetIndex + 3] = 255 - luminance
      }
      await sharp(rgba, {
        raw: { width: info.width, height: info.height, channels: 4 },
      })
        .png({ compressionLevel: 9, palette: true })
        .toFile(path.join(outputDir, 'proteus-alpha.png'))
    })
}

const cropBoxes = {
  flame: [140, 40, 390, 400],
  lion: [965, 135, 1310, 480],
  serpent: [1080, 350, 1448, 750],
  tree: [965, 660, 1400, 1255],
  waves: [0, 950, 1448, 1448],
  face: [515, 345, 900, 965],
}

/** Keep each crop at roughly 1000px on its long edge without upscaling. */
function cropDimensions(width, height) {
  const scale = Math.min(1, 1000 / Math.max(width, height))
  return {
    outputWidth: Math.max(1, Math.round(width * scale)),
    outputHeight: Math.max(1, Math.round(height * scale)),
  }
}

async function writeCrops() {
  const base = await renderSvg(1448)
  const scaleX = 1448 / viewWidth
  const scaleY = 1448 / viewHeight

  for (const [name, [left, top, right, bottom]] of Object.entries(cropBoxes)) {
    const width = right - left
    const height = bottom - top
    const { outputWidth, outputHeight } = cropDimensions(width, height)

    await sharp(base)
      .extract({
        left: Math.round(left * scaleX),
        top: Math.round(top * scaleY),
        width: Math.round(width * scaleX),
        height: Math.round(height * scaleY),
      })
      .resize({ width: outputWidth, height: outputHeight, fit: 'fill' })
      .flatten({ background: '#ffffff' })
      .webp({ quality: 82, effort: 6 })
      .toFile(path.join(outputDir, `proteus-${name}.webp`))
  }
}

await writeFullRasters()
await writeCrops()

const outputs = (await fs.readdir(outputDir)).sort()
let total = 0
for (const output of outputs) {
  const { size } = await fs.stat(path.join(outputDir, output))
  total += size
}
console.log(`Generated ${outputs.length} artwork assets in ${path.relative(root, outputDir)} (${(total / 1024 / 1024).toFixed(2)} MiB).`)
