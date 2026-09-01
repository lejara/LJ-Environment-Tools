import { useCallback, useEffect, useRef, useState } from 'react'

/** Pixels of horizontal drag per `step` of value change. */
const DRAG_PIXELS_PER_STEP = 4
/** Movement under this is treated as a click, not a drag. */
const DRAG_DEADZONE_PX = 2
/**
 * Safety net on a single event's movement. Engaging pointer lock can emit one
 * outsized `movementX` as the pointer is recentred, and that lone frame would
 * fling the value. Set well above any genuine flick — a fast drag is on the
 * order of tens of pixels per event, so this only ever catches a spike.
 */
const MAX_MOVEMENT_PX = 400

interface QuantityInputProps {
  label: string
  value: number
  onChange(value: number, isGestureStart: boolean): void
  step?: number
  min?: number
  max?: number
  /** Decimal places shown. Pixel fields want 0; normalized fields want 3. */
  precision?: number
  suffix?: string
  disabled?: boolean
}

/**
 * The shared value editor: a number field with increment/decrement buttons and
 * a horizontal drag-to-scrub on the label.
 *
 * `onChange` gets `isGestureStart` so the caller can push exactly one undo
 * entry per gesture — true on the first change of a drag or a button press,
 * false for every subsequent change while the drag continues. Without that, a
 * single drag would fill the history stack with hundreds of steps.
 */
export function QuantityInput({
  label,
  value,
  onChange,
  step = 1,
  min,
  max,
  precision = 0,
  suffix,
  disabled = false
}: QuantityInputProps): JSX.Element {
  const [draft, setDraft] = useState<string | null>(null)
  /**
   * The in-flight gesture. `travelled` accumulates movement deltas rather than
   * holding a start position — under pointer lock there is no absolute cursor
   * position to measure against.
   */
  const drag = useRef<{ travelled: number; startValue: number; moved: boolean } | null>(null)

  const clamp = useCallback(
    (next: number): number => {
      let out = next
      if (min !== undefined) out = Math.max(out, min)
      if (max !== undefined) out = Math.min(out, max)
      return out
    },
    [min, max]
  )

  const commit = useCallback(
    (next: number, isGestureStart: boolean): void => {
      if (Number.isNaN(next)) return
      onChange(clamp(next), isGestureStart)
    },
    [clamp, onChange]
  )

  /**
   * Drag-to-scrub, attached on pointerdown rather than through an effect —
   * `drag` is a ref, so mutating it doesn't re-render and an effect would never
   * fire to hook the listeners up.
   *
   * ## Why pointer lock
   *
   * Tracking `clientX` means the gesture dies the moment the cursor hits a
   * screen edge, which on a value like position-X is exactly when you still
   * want to keep going. Pointer lock detaches the pointer from the screen: the
   * cursor is hidden and parked, and `movementX` keeps arriving forever, so a
   * drag can run as far as you like in either direction.
   *
   * Deltas are accumulated rather than measured against a start position,
   * because under lock there is no meaningful absolute position to measure
   * from. If the lock is refused — it needs a user gesture and a focused
   * document — the same accumulation runs on unlocked `movementX`, which
   * behaves exactly as before and simply stops at the screen edge.
   *
   * Listeners live on window so the gesture survives the cursor leaving the
   * label, and are torn down on pointerup.
   */
  const startDrag = useCallback(
    (event: React.PointerEvent): void => {
      if (disabled) return

      const target = event.currentTarget as HTMLElement
      const state = { travelled: 0, startValue: value, moved: false }
      drag.current = state
      document.body.style.cursor = 'ew-resize'

      const onMove = (move: PointerEvent): void => {
        // Clamped: the frame that engages the lock can report a huge jump.
        const delta = Math.max(-MAX_MOVEMENT_PX, Math.min(move.movementX, MAX_MOVEMENT_PX))
        state.travelled += delta

        if (!state.moved && Math.abs(state.travelled) < DRAG_DEADZONE_PX) return
        // Only the first move of the gesture opens an undo entry, so a whole
        // drag collapses to one step instead of hundreds.
        const isGestureStart = !state.moved
        state.moved = true
        commit(
          state.startValue + (state.travelled / DRAG_PIXELS_PER_STEP) * step,
          isGestureStart
        )
      }

      const finish = (): void => {
        drag.current = null
        document.body.style.cursor = ''
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', finish)
        document.removeEventListener('pointerlockchange', onLockChange)
        if (document.pointerLockElement) document.exitPointerLock()
      }

      /**
       * Esc releases the lock without a pointerup. Ending the gesture here
       * stops a drag continuing invisibly with the cursor back on screen.
       */
      function onLockChange(): void {
        if (!document.pointerLockElement && drag.current === state) finish()
      }

      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', finish)
      document.addEventListener('pointerlockchange', onLockChange)

      // `unadjustedMovement` asks for raw deltas with OS mouse acceleration
      // removed, which keeps scrubbing linear. Not everywhere supports it, so
      // fall back to a plain lock, then to no lock at all.
      const lock = target.requestPointerLock({ unadjustedMovement: true }) as unknown
      if (lock instanceof Promise) {
        lock.catch(() => {
          try {
            target.requestPointerLock()
          } catch {
            /* no lock: the drag still works, it just stops at the screen edge */
          }
        })
      }
    },
    [disabled, value, step, commit]
  )

  // A drag in flight when the control unmounts would leave the cursor hidden
  // and the page stuck in ew-resize.
  useEffect(
    () => () => {
      if (!drag.current) return
      document.body.style.cursor = ''
      if (document.pointerLockElement) document.exitPointerLock()
    },
    []
  )

  const shown = draft ?? value.toFixed(precision)

  return (
    <div className={`qty ${disabled ? 'qty--disabled' : ''}`}>
      <span className="qty__label" onPointerDown={startDrag} title="Drag horizontally to scrub">
        {label}
      </span>
      <div className="qty__body">
        <input
          className="qty__input"
          type="text"
          inputMode="decimal"
          value={shown}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => {
            if (draft !== null) commit(Number.parseFloat(draft), true)
            setDraft(null)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.currentTarget.blur()
            } else if (event.key === 'Escape') {
              setDraft(null)
              event.currentTarget.blur()
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              commit(value + step, true)
            } else if (event.key === 'ArrowDown') {
              event.preventDefault()
              commit(value - step, true)
            }
          }}
        />
        {suffix ? <span className="qty__suffix">{suffix}</span> : null}
        <div className="qty__steppers">
          <button type="button" disabled={disabled} onClick={() => commit(value + step, true)} tabIndex={-1}>
            ▲
          </button>
          <button type="button" disabled={disabled} onClick={() => commit(value - step, true)} tabIndex={-1}>
            ▼
          </button>
        </div>
      </div>
    </div>
  )
}
