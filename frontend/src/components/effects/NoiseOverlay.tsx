/** Fixed 3% film-grain overlay used across the cobalt landing surface. */
const NOISE_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='260' height='260'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"
export function NoiseOverlay({ opacity = 0.03 }: { opacity?: number }) {
  return <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-[100]" style={{ opacity, mixBlendMode: 'overlay', backgroundImage: `url("${NOISE_SVG}")`, backgroundSize: '260px 260px', backgroundRepeat: 'repeat' }} />
}
export default NoiseOverlay
