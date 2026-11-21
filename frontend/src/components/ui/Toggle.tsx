import { cn } from '@/lib/utils'

interface ToggleProps { checked: boolean; onChange: (value: boolean) => void; label?: string; hint?: string; disabled?: boolean; className?: string; id?: string }

export function Toggle({ checked, onChange, label, hint, disabled, className, id }: ToggleProps) {
  return (
    <div className={cn('flex items-center gap-3', className)}>
      {label ? <div className="leading-tight"><label htmlFor={id} className="block cursor-pointer text-[13px] font-medium text-paper">{label}</label>{hint ? <span className="block text-[12px] text-paper-muted">{hint}</span> : null}</div> : null}
      <button id={id} type="button" role="switch" aria-checked={checked} aria-label={label ?? 'Toggle'} disabled={disabled} onClick={() => onChange(!checked)} className={cn('relative h-6 w-11 shrink-0 rounded-pill border transition-all duration-300 ease-proteus disabled:opacity-40', checked ? 'border-foam/60 bg-foam/20' : 'border-hairline bg-cobalt-deep hover:bg-paper/10')}>
        <span className={cn('absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full transition-all duration-300 ease-proteus', checked ? 'left-[1.45rem] bg-foam' : 'left-[3px] bg-paper-muted')} />
      </button>
    </div>
  )
}
export default Toggle
