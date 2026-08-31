import { useEffect, useRef } from 'react'

interface LorenzCanvasProps {
  className?: string
  opacity?: number
  interactive?: boolean
  scaleMultiplier?: number
}

/**
 * 3D 洛伦兹吸引子（Lorenz Attractor）拓扑微粒流场 Canvas
 * 常微分方程组：
 *   dx/dt = σ(y - x)
 *   dy/dt = x(ρ - z) - y
 *   dz/dt = xy - βz
 * 其中 σ=10, ρ=28, β=8/3
 */
export default function LorenzCanvas({
  className = '',
  opacity = 0.6,
  interactive = true,
  scaleMultiplier = 1,
}: LorenzCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const mouseRef = useRef<{ x: number; y: number; active: boolean }>({ x: 0, y: 0, active: false })

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationFrameId = 0
    let width = (canvas.width = canvas.offsetWidth || 300)
    let height = (canvas.height = canvas.offsetHeight || 300)

    const handleResize = () => {
      if (!canvas) return
      width = canvas.width = canvas.offsetWidth
      height = canvas.height = canvas.offsetHeight
    }

    const ro = new ResizeObserver(handleResize)
    ro.observe(canvas)

    // 预计算洛伦兹点集
    const sigma = 10
    const rho = 28
    const beta = 8 / 3
    const dt = 0.008
    const numPoints = 1000

    const points: { x: number; y: number; z: number }[] = []
    let cx = 0.1
    let cy = 0
    let cz = 0

    for (let i = 0; i < numPoints; i++) {
      const dx = sigma * (cy - cx) * dt
      const dy = (cx * (rho - cz) - cy) * dt
      const dz = (cx * cy - beta * cz) * dt
      cx += dx
      cy += dy
      cz += dz
      points.push({ x: cx, y: cy, z: cz - 24 }) // 将吸引子中心沉降至原点
    }

    let angleY = 0
    let angleX = 0.3
    let targetAngleY = 0
    let targetAngleX = 0.3

    const render = () => {
      ctx.clearRect(0, 0, width, height)

      // 角度平滑旋转
      targetAngleY += 0.006
      if (mouseRef.current.active && interactive) {
        const mx = (mouseRef.current.x / width - 0.5) * 2
        const my = (mouseRef.current.y / height - 0.5) * 2
        targetAngleX = 0.3 + my * 0.4
        targetAngleY += mx * 0.01
      }
      angleY += (targetAngleY - angleY) * 0.05
      angleX += (targetAngleX - angleX) * 0.05

      const cosY = Math.cos(angleY)
      const sinY = Math.sin(angleY)
      const cosX = Math.cos(angleX)
      const sinX = Math.sin(angleX)

      const scale = Math.min(width, height) * 0.02 * scaleMultiplier
      const centerX = width / 2
      const centerY = height / 2

      ctx.lineWidth = 1.2
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'

      // 投影并绘制流线
      for (let i = 1; i < points.length; i += 2) {
        const p1 = points[i - 1]
        const p2 = points[i]

        // 3D 旋转变换
        // Y 轴旋转
        const x1_y = p1.x * cosY + p1.z * sinY
        const z1_y = -p1.x * sinY + p1.z * cosY
        // X 轴旋转
        const y1_x = p1.y * cosX - z1_y * sinX
        const z1_final = p1.y * sinX + z1_y * cosX

        const x2_y = p2.x * cosY + p2.z * sinY
        const z2_y = -p2.x * sinY + p2.z * cosY
        const y2_x = p2.y * cosX - z2_y * sinX
        const z2_final = p2.y * sinX + z2_y * cosX

        // 透视投影
        const fov = 120
        const proj1 = fov / (fov + z1_final + 30)
        const proj2 = fov / (fov + z2_final + 30)

        const sx1 = centerX + x1_y * scale * proj1
        const sy1 = centerY + y1_x * scale * proj1
        const sx2 = centerX + x2_y * scale * proj2
        const sy2 = centerY + y2_x * scale * proj2

        // 沿流线的量子色彩渐变 (Cyan -> Blue -> Purple -> Laser)
        const progress = i / points.length
        const alpha = Math.max(0.08, Math.min(0.9, (z1_final + 25) / 50)) * opacity

        ctx.beginPath()
        ctx.moveTo(sx1, sy1)
        ctx.lineTo(sx2, sy2)

        if (progress < 0.35) {
          ctx.strokeStyle = `rgba(56, 189, 248, ${alpha})` // Cyan
        } else if (progress < 0.7) {
          ctx.strokeStyle = `rgba(96, 165, 250, ${alpha})` // Blue
        } else if (progress < 0.92) {
          ctx.strokeStyle = `rgba(192, 132, 252, ${alpha})` // Purple
        } else {
          ctx.strokeStyle = `rgba(255, 255, 255, ${alpha * 1.2})` // Laser White
        }

        ctx.stroke()
      }

      animationFrameId = requestAnimationFrame(render)
    }

    render()

    const onPointerMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect()
      mouseRef.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        active: true,
      }
    }

    const onPointerLeave = () => {
      mouseRef.current.active = false
    }

    if (interactive) {
      canvas.addEventListener('pointermove', onPointerMove)
      canvas.addEventListener('pointerleave', onPointerLeave)
    }

    return () => {
      cancelAnimationFrame(animationFrameId)
      ro.disconnect()
      if (interactive) {
        canvas.removeEventListener('pointermove', onPointerMove)
        canvas.removeEventListener('pointerleave', onPointerLeave)
      }
    }
  }, [opacity, interactive, scaleMultiplier])

  return (
    <canvas
      ref={canvasRef}
      className={`lorenz-canvas ${className}`}
      style={{
        pointerEvents: interactive ? 'auto' : 'none',
        display: 'block',
        width: '100%',
        height: '100%',
      }}
    />
  )
}
