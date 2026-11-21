import { X } from 'lucide-react'
import { useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { friendlyName } from '@/lib/status'
import { cn, isValidEmail } from '@/lib/utils'
import type { RecipientContact } from '@/types'

export interface RecipientInputProps {
  label: 'To' | 'Cc' | 'Bcc'
  values: string[]
  onChange: (values: string[]) => void
  contacts: RecipientContact[]
  disabled?: boolean
  placeholder?: string
}

/**
 * Chip-based recipient input with contact autocomplete, email validation and
 * paste-multiple support (comma / semicolon / newline separated).
 */
export function RecipientInput({ label, values, onChange, contacts, disabled = false, placeholder }: RecipientInputProps) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const [invalid, setInvalid] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const suggestions = useMemo(() => {
    const query = text.trim().toLowerCase()
    if (!query) return []
    return contacts
      .filter((contact) => !values.includes(contact.email))
      .filter((contact) => contact.name.toLowerCase().includes(query) || contact.email.toLowerCase().includes(query))
      .slice(0, 6)
  }, [text, contacts, values])

  const addEmail = (raw: string): boolean => {
    const email = raw.trim().toLowerCase()
    if (!email) return true
    if (!isValidEmail(email)) {
      setInvalid(true)
      return false
    }
    setInvalid(false)
    if (!values.includes(email)) onChange([...values, email])
    setText('')
    setOpen(false)
    return true
  }

  const addMany = (raw: string) => {
    const parts = raw.split(/[,;\n]+/).map((part) => part.trim()).filter(Boolean)
    const valid: string[] = []
    let anyInvalid = false
    for (const part of parts) {
      if (isValidEmail(part)) {
        const email = part.toLowerCase()
        if (!values.includes(email) && !valid.includes(email)) valid.push(email)
      } else anyInvalid = true
    }
    if (valid.length > 0) onChange([...values, ...valid])
    setInvalid(anyInvalid)
    setText(anyInvalid ? parts.filter((part) => !isValidEmail(part)).join(', ') : '')
    setOpen(false)
  }

  const removeAt = (index: number) => onChange(values.filter((_, i) => i !== index))

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' && suggestions.length > 0) {
      event.preventDefault()
      setOpen(true)
      setActiveIndex((index) => (index + 1) % suggestions.length)
    } else if (event.key === 'ArrowUp' && suggestions.length > 0) {
      event.preventDefault()
      setActiveIndex((index) => (index - 1 + suggestions.length) % suggestions.length)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (open && suggestions[activeIndex]) addEmail(suggestions[activeIndex]!.email)
      else addEmail(text)
    } else if (event.key === ',' || event.key === ';') {
      event.preventDefault()
      addEmail(text)
    } else if (event.key === 'Escape') {
      setOpen(false)
    } else if (event.key === 'Backspace' && text === '' && values.length > 0) {
      removeAt(values.length - 1)
    }
  }

  return (
    <div className="relative">
      <div
        className={cn(
          'flex flex-wrap items-center gap-1.5 rounded-card border bg-white/30 px-2.5 py-2 transition-colors focus-within:border-ink/60',
          invalid ? 'border-ember-ink' : 'border-ink-hairline',
          disabled && 'opacity-60',
        )}
        onClick={() => inputRef.current?.focus()}
      >
        <span className="w-9 shrink-0 font-mono text-[12px] uppercase tracking-[0.1em] text-ink-muted">{label}</span>
        {values.map((email, index) => (
          <span key={email} className="inline-flex max-w-full items-center gap-1 rounded-pill border border-ink-hairline bg-paper px-2.5 py-0.5 text-[12px] text-ink" title={email}>
            <span className="truncate">{friendlyName(email)}</span>
            {!disabled ? (
              <button type="button" aria-label={`Remove ${email}`} onClick={(event) => { event.stopPropagation(); removeAt(index) }} className="shrink-0 text-ink-muted hover:text-ember-ink">
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </span>
        ))}
        <input
          ref={inputRef}
          value={text}
          disabled={disabled}
          onChange={(event) => { setText(event.target.value); setInvalid(false); setOpen(true); setActiveIndex(0) }}
          onKeyDown={handleKeyDown}
          onFocus={() => text.trim() && setOpen(true)}
          onBlur={() => { setOpen(false); if (text.trim()) addEmail(text) }}
          onPaste={(event) => {
            const pasted = event.clipboardData.getData('text')
            if (/[,;\n]/.test(pasted)) { event.preventDefault(); addMany(pasted) }
          }}
          placeholder={values.length === 0 ? (placeholder ?? 'name@company.com') : ''}
          aria-label={`${label} recipients`}
          aria-invalid={invalid}
          role="combobox"
          aria-expanded={open && suggestions.length > 0}
          aria-autocomplete="list"
          className="min-w-[8rem] flex-1 bg-transparent py-0.5 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none"
        />
      </div>
      {invalid ? <p className="mt-1 text-[12px] text-ember-ink">That doesn’t look like an email address yet.</p> : null}
      {open && suggestions.length > 0 ? (
        <ul role="listbox" aria-label={`${label} contact suggestions`} className="absolute left-0 right-0 top-[calc(100%+4px)] z-30 max-h-52 overflow-y-auto rounded-card border border-ink-hairline bg-paper">
          {suggestions.map((contact, index) => (
            <li key={contact.id} role="option" aria-selected={index === activeIndex}>
              <button
                type="button"
                onMouseDown={(event) => { event.preventDefault(); addEmail(contact.email) }}
                onMouseEnter={() => setActiveIndex(index)}
                className={cn('flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left', index === activeIndex ? 'bg-foam/60' : 'hover:bg-ink/5')}
              >
                <span className="truncate text-[13px] text-ink">{contact.name}</span>
                <span className="shrink-0 font-mono text-[12px] text-ink-muted">{contact.email}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export default RecipientInput